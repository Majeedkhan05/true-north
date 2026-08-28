"""FastAPI backend wiring Email/n8n -> PDF -> Gemini -> Validation -> Draft -> DB.

Endpoints:
  POST /webhook/document          (n8n posts a PDF + brokerage_id)
  POST /check-duplicate           (n8n FLOW 1 cheap SHA-256 pre-check)
  POST /audit                     (n8n logs pipeline events back, PII-masked)
  GET  /approve/{token}           (JWT token approval — n8n approval_flow)
  POST /retry/process             (re-process a failed doc — n8n failure_flow)
  GET  /brokerage/documents
  GET  /brokerage/document/{id}
  POST /brokerage/approve/{id}
  POST /billing/checkout
  POST /stripe/webhook
  POST /admin/brokerage           (onboarding)
  GET  /admin/metrics             (MRR, active subs, health)
  GET  /healthz

n8n control-plane contract (status codes routed on):
  200 SUCCESS · 429 QUOTA_EXCEEDED · 403 SUBSCRIPTION_INACTIVE ·
  400 INVALID_PDF · 409 DUPLICATE · 500 ERROR
Gating errors return a structured top-level body ({error, language, links})
so n8n can render bilingual emails — see structured_http_exception_handler.

Cross-cutting:
  - check_subscription_active() gates all processing (403 when inactive).
  - log_audit() records every action with PII masked.
  - RLS: per-request `app.brokerage_id` GUC set on Postgres connections.
"""
from __future__ import annotations

import datetime as dt
import logging

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from auth import TokenExpired, TokenInvalid, create_approval_token, decode_approval_token
from config import PLANS, settings
from database import get_db, init_db
from email_draft import build_draft_email
from gemini_client import extract_document
from i18n import language_for_postal_code, normalize_language
from models import (
    ApprovalResult,
    ApproveResult,
    AuditEvent,
    AuditLog,
    Brokerage,
    BrokerageCreate,
    BrokerageOut,
    CheckDuplicateRequest,
    CheckDuplicateResult,
    Document,
    DocumentOut,
    ProcessResult,
    RetryRequest,
)
from pii_utils import mask_for_logs, validate_for_db
from storage import download_pdf, extract_text, sha256_hash, upload_pdf
from stripe_integration import (
    check_subscription_active,
    create_checkout_session,
    handle_webhook_event,
)
from validation import validate_extraction

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("brokerage.api")

# Global rule (matches n8n control plane): max_retries = 2
MAX_RETRIES = 2

app = FastAPI(title="Brokerage-AI", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


_rl_hits: dict[str, list[float]] = {}

@app.middleware("http")
async def rate_limiter(request, call_next):
    limit = settings.rate_limit_per_min
    if limit and request.method == "POST":
        import time as _t
        ip = request.client.host if request.client else "?"
        now = _t.time()
        hits = [t for t in _rl_hits.get(ip, []) if now - t < 60]
        if len(hits) >= limit:
            return JSONResponse(status_code=429, content={"error": "RATE_LIMITED"})
        hits.append(now)
        _rl_hits[ip] = hits
    return await call_next(request)


@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return resp


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    """Admin gate: enforced only when ADMIN_API_KEY is configured (prod)."""
    if settings.admin_api_key and x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="ADMIN_AUTH_REQUIRED")


@app.on_event("startup")
def _startup() -> None:
    # For SQLite/offline demos, create tables from ORM metadata.
    if settings.database_url.startswith("sqlite"):
        init_db()


@app.exception_handler(StarletteHTTPException)
async def structured_http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Allow handlers to raise HTTPException(detail={...}) and have the dict
    become the TOP-LEVEL response body — so the n8n control plane can read
    `body.language`, `body.upgrade_url`, etc. directly. String details keep the
    default `{"detail": "..."}` shape.
    """
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Any uncaught error -> 500 with the n8n contract string "ERROR"."""
    logger.exception("Unhandled error: %s", type(exc).__name__)
    return JSONResponse(status_code=500, content={"error": "ERROR"})


# ---------------------------------------------------------------------------
#  Helpers: RLS scoping + audit logging
# ---------------------------------------------------------------------------
def _scope_rls(db: Session, brokerage_id: str | None) -> None:
    """Set the request-scoped brokerage id so Postgres RLS policies apply.

    No-op on SQLite (which has no RLS); the ORM queries still filter by
    brokerage_id, so isolation holds either way.
    """
    if brokerage_id and db.bind.dialect.name == "postgresql":
        db.execute(text("SET app.brokerage_id = :bid"), {"bid": brokerage_id})


def log_audit(
    db: Session,
    *,
    brokerage_id: str | None,
    document_id: str | None,
    action: str,
    ip_address: str | None,
) -> None:
    """Persist an audit log row. PII in the action text is masked first."""
    entry = AuditLog(
        brokerage_id=brokerage_id,
        document_id=document_id,
        action=mask_for_logs(action),
        ip_address=ip_address,
        timestamp=dt.datetime.now(dt.timezone.utc),
    )
    db.add(entry)
    db.commit()


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def doc_limit_for_plan(plan: str) -> int | None:
    """Quota for a plan; None == unlimited (enterprise)."""
    return PLANS.get(plan, {}).get("monthly_docs")


def reset_quota_if_new_cycle(db: Session, brokerage: Brokerage) -> None:
    """Roll docs_used back to 0 at the start of a new 30-day billing cycle."""
    now = dt.datetime.now(dt.timezone.utc)
    start = brokerage.quota_period_start
    if start is None:
        brokerage.quota_period_start = now
        db.commit()
        return
    if start.tzinfo is None:
        start = start.replace(tzinfo=dt.timezone.utc)
    if (now - start).days >= 30:
        brokerage.docs_used = 0
        brokerage.quota_period_start = now
        db.commit()


# ===========================================================================
#  Document processing
# ===========================================================================
@app.post("/webhook/document", response_model=ProcessResult)
async def process_document(
    request: Request,
    brokerage_id: str = Form(...),
    file: UploadFile = File(...),
    x_webhook_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    # 1) authenticate the n8n caller
    if settings.webhook_shared_secret and x_webhook_secret != settings.webhook_shared_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    brokerage = db.query(Brokerage).filter(Brokerage.id == brokerage_id).first()
    if not brokerage:
        raise HTTPException(status_code=404, detail="Brokerage not found")
    _scope_rls(db, brokerage_id)
    ip = _client_ip(request)
    language = normalize_language(brokerage.language)

    # 2) 403 SUBSCRIPTION_INACTIVE — Stripe gate blocks ALL processing
    if not check_subscription_active(db, brokerage_id):
        log_audit(db, brokerage_id=brokerage_id, document_id=None,
                  action="process_blocked_subscription_inactive", ip_address=ip)
        raise HTTPException(status_code=403, detail={
            "error": "SUBSCRIPTION_INACTIVE",
            "language": language,
            "broker_email": brokerage.email,
            "billing_portal_url": settings.stripe_billing_portal_url,
        })

    # 3) 429 QUOTA_EXCEEDED — cycle-aware quota (doc_limit / docs_used)
    reset_quota_if_new_cycle(db, brokerage)
    limit = brokerage.doc_limit if brokerage.doc_limit is not None else doc_limit_for_plan(brokerage.plan)
    if limit is not None and brokerage.docs_used >= limit:
        log_audit(db, brokerage_id=brokerage_id, document_id=None,
                  action="process_blocked_quota_exceeded", ip_address=ip)
        raise HTTPException(status_code=429, detail={
            "error": "QUOTA_EXCEEDED",
            "language": language,
            "broker_email": brokerage.email,
            "upgrade_url": settings.stripe_upgrade_url,
        })

    # 4) 400 INVALID_PDF — must be a PDF (extension or content-type)
    is_pdf = (file.filename or "").lower().endswith(".pdf") or (
        file.content_type == "application/pdf"
    )
    if not is_pdf:
        log_audit(db, brokerage_id=brokerage_id, document_id=None,
                  action="process_blocked_invalid_pdf", ip_address=ip)
        raise HTTPException(status_code=400, detail={
            "error": "INVALID_PDF",
            "language": language,
            "broker_email": brokerage.email,
        })

    raw = await file.read()
    if not raw or not raw.lstrip()[:4].startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail={
            "error": "INVALID_PDF", "language": language, "broker_email": brokerage.email,
        })
    if len(raw) > settings.max_upload_mb * 1024 * 1024:
        log_audit(db, brokerage_id=brokerage_id, document_id=None,
                  action="process_blocked_file_too_large", ip_address=ip)
        raise HTTPException(status_code=400, detail={
            "error": "FILE_TOO_LARGE", "language": language, "broker_email": brokerage.email,
        })

    # 5) 409 DUPLICATE — SHA256 dedup (scoped per brokerage). Stop silently.
    file_hash = sha256_hash(raw)
    existing = (
        db.query(Document)
        .filter(Document.brokerage_id == brokerage_id, Document.file_hash == file_hash)
        .first()
    )
    if existing:
        log_audit(db, brokerage_id=brokerage_id, document_id=existing.id,
                  action="duplicate_skipped", ip_address=ip)
        raise HTTPException(status_code=409, detail={
            "error": "DUPLICATE",
            "language": language,
            "document_id": existing.id,
        })

    # 6) store file + extract text (pdfplumber -> OCR fallback)
    file_path = upload_pdf(brokerage_id, file_hash, raw)
    document_text = extract_text(raw)

    # 7) Gemini extraction (language = brokerage preference)
    extracted = extract_document(document_text, language)

    # 8) validation (policy regex, dates, numerics) + PII guard
    extracted, _issues = validate_extraction(extracted)
    extracted = validate_for_db(extracted)
    confidence = float(extracted.get("confidence", 0.0))

    # 9) draft email in brokerage language (with legal footer)
    draft = build_draft_email(language, extracted)

    # 10) persist everything + count against quota
    doc = Document(
        brokerage_id=brokerage_id,
        file_hash=file_hash,
        file_path=file_path,
        extracted_json=extracted,
        confidence_score=confidence,
        status="processed",
        draft_email=draft,
    )
    from features import run_compliance, run_opportunities
    doc.compliance = run_compliance(doc, brokerage)
    doc.opportunities = run_opportunities(doc)
    db.add(doc)
    brokerage.docs_used = (brokerage.docs_used or 0) + 1
    db.commit()
    db.refresh(doc)

    # 11) signed approval token for the email link -> GET /approve/{token}
    approval_token = create_approval_token(doc.id, brokerage_id)

    log_audit(db, brokerage_id=brokerage_id, document_id=doc.id,
              action=f"document_processed confidence={confidence}", ip_address=ip)

    return ProcessResult(
        document_id=doc.id,
        extracted_json=extracted,
        draft_email=draft,
        confidence_score=confidence,
        duplicate=False,
        language=language,
        broker_email=brokerage.email,
        approval_token=approval_token,
    )


# ===========================================================================
#  n8n FLOW 1 helpers: /check-duplicate (cheap pre-check) + /audit (log back)
# ===========================================================================
def _require_webhook_secret(secret: str | None) -> None:
    if settings.webhook_shared_secret and secret != settings.webhook_shared_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


@app.post("/check-duplicate", response_model=CheckDuplicateResult)
def check_duplicate(
    payload: CheckDuplicateRequest,
    x_webhook_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Read-only SHA-256 dedup pre-check so n8n can skip Gemini spend on dups.
    /webhook/document remains the authoritative dedup (409) safety net.
    """
    _require_webhook_secret(x_webhook_secret)
    _scope_rls(db, payload.brokerage_id)
    existing = (
        db.query(Document)
        .filter(
            Document.brokerage_id == payload.brokerage_id,
            Document.file_hash == payload.file_hash,
        )
        .first()
    )
    return CheckDuplicateResult(
        duplicate=existing is not None,
        document_id=existing.id if existing else None,
    )


@app.post("/audit")
def audit_event(
    event: AuditEvent,
    x_webhook_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """n8n logs pipeline events back here. log_audit() masks PII; we additionally
    refuse to store anything but the (already non-PII) action string."""
    _require_webhook_secret(x_webhook_secret)
    _scope_rls(db, event.brokerage_id)
    log_audit(db, brokerage_id=event.brokerage_id, document_id=event.document_id,
              action=event.action, ip_address=event.ip_address)
    return {"logged": True}


# ===========================================================================
#  Brokerage read endpoints
# ===========================================================================
@app.get("/brokerage/documents", response_model=list[DocumentOut])
def list_documents(brokerage_id: str, db: Session = Depends(get_db)):
    _scope_rls(db, brokerage_id)
    docs = (
        db.query(Document)
        .filter(Document.brokerage_id == brokerage_id)
        .order_by(Document.created_at.desc())
        .all()
    )
    return docs


@app.get("/brokerage/document/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, brokerage_id: str, db: Session = Depends(get_db)):
    _scope_rls(db, brokerage_id)
    doc = (
        db.query(Document)
        .filter(Document.id == document_id, Document.brokerage_id == brokerage_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _notify_n8n_approval(db: Session, doc: Document) -> None:
    """Best-effort POST to n8n FLOW 2 after a broker approval so n8n sends the
    final client email. Never raises — approval must succeed regardless."""
    url = settings.n8n_approval_webhook_url
    if not url or settings.demo_mode:
        return
    brokerage = db.query(Brokerage).filter(Brokerage.id == doc.brokerage_id).first()
    extracted = doc.extracted_json or {}
    payload = {
        "brokerage_id": doc.brokerage_id,
        "document_id": doc.id,
        "language": normalize_language(brokerage.language if brokerage else "en"),
        "broker_email": brokerage.email if brokerage else None,
        # client_email is null unless the extraction captured one; n8n then
        # routes the final email to the broker to forward.
        "client_email": extracted.get("client_email"),
        "final_email": doc.draft_email or "",
    }
    try:
        import requests

        requests.post(
            url,
            json=payload,
            headers={"x-webhook-secret": settings.webhook_shared_secret},
            timeout=8,
        )
    except Exception as exc:  # noqa: BLE001 — notification is best-effort
        logger.warning("n8n approval notify failed for %s: %s", doc.id, exc)


@app.post("/brokerage/approve/{document_id}", response_model=ApproveResult)
def approve_document(
    document_id: str,
    request: Request,
    brokerage_id: str = Form(...),
    db: Session = Depends(get_db),
):
    _scope_rls(db, brokerage_id)
    doc = (
        db.query(Document)
        .filter(Document.id == document_id, Document.brokerage_id == brokerage_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    already = doc.status == "approved"
    doc.status = "approved"
    db.commit()
    log_audit(db, brokerage_id=brokerage_id, document_id=doc.id,
              action="document_approved", ip_address=_client_ip(request))
    if not already:  # fire n8n FLOW 2 once (idempotent on re-approve)
        _notify_n8n_approval(db, doc)
    return ApproveResult(
        document_id=doc.id,
        status="approved",
        approved_at=dt.datetime.now(dt.timezone.utc),
    )


# ===========================================================================
#  Token approval (JWT)  — n8n approval_flow calls GET /approve/{token}
# ===========================================================================
@app.get("/approve/{token}", response_model=ApprovalResult)
def approve_with_token(token: str, request: Request, db: Session = Depends(get_db)):
    # 401 with string detail -> body {"detail": "TOKEN_EXPIRED" | "INVALID_TOKEN"}
    try:
        payload = decode_approval_token(token)
    except TokenExpired:
        raise HTTPException(status_code=401, detail="TOKEN_EXPIRED")
    except TokenInvalid:
        raise HTTPException(status_code=401, detail="INVALID_TOKEN")

    document_id = payload["document_id"]
    brokerage_id = payload["brokerage_id"]
    _scope_rls(db, brokerage_id)

    doc = (
        db.query(Document)
        .filter(Document.id == document_id, Document.brokerage_id == brokerage_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="DOCUMENT_NOT_FOUND")

    brokerage = db.query(Brokerage).filter(Brokerage.id == brokerage_id).first()
    language = normalize_language(brokerage.language if brokerage else "en")

    # Double-approval guard: status == approved means the token was already used.
    # Contract: return 200 {"status": "already_approved"} (idempotent, not an error).
    if doc.status == "approved":
        log_audit(db, brokerage_id=brokerage_id, document_id=doc.id,
                  action="approve_token_already_used", ip_address=_client_ip(request))
        return ApprovalResult(status="already_approved", document_id=doc.id, language=language)

    doc.status = "approved"
    db.commit()
    log_audit(db, brokerage_id=brokerage_id, document_id=doc.id,
              action="document_approved_via_token", ip_address=_client_ip(request))
    _notify_n8n_approval(db, doc)  # fire n8n FLOW 2 (final client email)
    return ApprovalResult(status="approved", document_id=doc.id, language=language)


# ===========================================================================
#  Retry — n8n failure_flow calls POST /retry/process for a failed document
# ===========================================================================
@app.post("/retry/process", response_model=ProcessResult)
def retry_process(
    payload: RetryRequest,
    request: Request,
    x_brokerage_id: str | None = Header(default=None),
    x_webhook_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    if settings.webhook_shared_secret and x_webhook_secret != settings.webhook_shared_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    if not payload.document_id:
        # Nothing to retry without an id (pre-persist 500s escalate to admin in n8n).
        raise HTTPException(status_code=404, detail={"error": "NO_DOCUMENT_ID"})

    _scope_rls(db, x_brokerage_id)
    q = db.query(Document).filter(Document.id == payload.document_id)
    if x_brokerage_id:
        q = q.filter(Document.brokerage_id == x_brokerage_id)
    doc = q.first()
    if not doc:
        raise HTTPException(status_code=404, detail={"error": "DOCUMENT_NOT_FOUND"})

    brokerage = db.query(Brokerage).filter(Brokerage.id == doc.brokerage_id).first()
    language = normalize_language(brokerage.language if brokerage else "en")
    ip = _client_ip(request)

    # 400 MAX_RETRIES_EXCEEDED — stop the loop after MAX_RETRIES attempts.
    if (doc.retry_count or 0) >= MAX_RETRIES:
        log_audit(db, brokerage_id=doc.brokerage_id, document_id=doc.id,
                  action=f"retry_blocked_max_retries count={doc.retry_count}", ip_address=ip)
        raise HTTPException(status_code=400, detail={
            "error": "MAX_RETRIES_EXCEEDED",
            "document_id": doc.id,
            "retry_count": doc.retry_count,
        })

    # Idempotent: if already past 'failed', just return current state.
    if doc.status in ("processed", "approved"):
        return ProcessResult(
            document_id=doc.id,
            extracted_json=doc.extracted_json or {},
            draft_email=doc.draft_email or "",
            confidence_score=doc.confidence_score or 0.0,
            language=language,
            broker_email=brokerage.email if brokerage else None,
            approval_token=create_approval_token(doc.id, doc.brokerage_id),
        )

    # Count this retry attempt (source of truth for the 400 guard above).
    doc.retry_count = (doc.retry_count or 0) + 1

    # Re-run extraction from the stored PDF if we can fetch it; else re-validate
    # whatever was captured before the failure.
    raw = download_pdf(doc.file_path)
    if raw:
        extracted = extract_document(extract_text(raw), language)
    else:
        extracted = doc.extracted_json or {"confidence": 0}

    extracted, _issues = validate_extraction(extracted)
    extracted = validate_for_db(extracted)
    confidence = float(extracted.get("confidence", 0.0))
    draft = build_draft_email(language, extracted)

    doc.extracted_json = extracted
    doc.confidence_score = confidence
    doc.draft_email = draft
    doc.status = "processed"
    db.commit()
    log_audit(db, brokerage_id=doc.brokerage_id, document_id=doc.id,
              action="document_reprocessed_retry", ip_address=ip)

    return ProcessResult(
        document_id=doc.id,
        extracted_json=extracted,
        draft_email=draft,
        confidence_score=confidence,
        language=language,
        broker_email=brokerage.email if brokerage else None,
        approval_token=create_approval_token(doc.id, doc.brokerage_id),
    )


# ===========================================================================
#  Billing
# ===========================================================================
@app.post("/billing/checkout")
def billing_checkout(
    brokerage_id: str = Form(...),
    plan: str = Form(...),
    db: Session = Depends(get_db),
):
    brokerage = db.query(Brokerage).filter(Brokerage.id == brokerage_id).first()
    if not brokerage:
        raise HTTPException(status_code=404, detail="Brokerage not found")
    if plan not in PLANS:
        raise HTTPException(status_code=400, detail="Invalid plan")
    url = create_checkout_session(db, brokerage, plan)
    return {"checkout_url": url}


@app.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: Session = Depends(get_db),
):
    payload = await request.body()
    try:
        result = handle_webhook_event(payload, stripe_signature or "", db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Stripe webhook error: %s", exc)
        raise HTTPException(status_code=400, detail="Webhook verification failed")
    return result


# ===========================================================================
#  Admin: onboarding + metrics
# ===========================================================================
@app.post("/admin/brokerage", response_model=BrokerageOut)
def onboard_brokerage(payload: BrokerageCreate, db: Session = Depends(get_db), _admin: None = Depends(require_admin)):
    if db.query(Brokerage).filter(Brokerage.email == payload.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    language = normalize_language(
        payload.language or language_for_postal_code(payload.postal_code)
    )
    brokerage = Brokerage(
        email=payload.email,
        name=payload.name,
        postal_code=payload.postal_code,
        plan=payload.plan,
        language=language,
        status="inactive",
        doc_limit=doc_limit_for_plan(payload.plan),
        docs_used=0,
        quota_period_start=dt.datetime.now(dt.timezone.utc),
    )
    db.add(brokerage)
    db.commit()
    db.refresh(brokerage)

    # Pre-create the Stripe customer so checkout is one click later.
    from stripe_integration import ensure_customer

    ensure_customer(db, brokerage)
    db.refresh(brokerage)

    log_audit(db, brokerage_id=brokerage.id, document_id=None,
              action="brokerage_onboarded", ip_address=None)
    return brokerage


@app.get("/admin/brokerages", response_model=list[BrokerageOut])
def list_brokerages(db: Session = Depends(get_db), _admin: None = Depends(require_admin)):
    return db.query(Brokerage).order_by(Brokerage.created_at.desc()).all()


@app.get("/admin/metrics")
def admin_metrics(db: Session = Depends(get_db), _admin: None = Depends(require_admin)):
    from config import ACTIVE_SUB_STATUSES

    brokerages = db.query(Brokerage).all()
    active = [b for b in brokerages if b.status in ACTIVE_SUB_STATUSES]
    mrr = sum(PLANS[b.plan]["price_cad"] for b in active if b.plan in PLANS)

    # crude system health: can we reach the DB + is config present?
    health = "green"
    if not (settings.gemini_api_key or settings.demo_mode):
        health = "yellow"
    if not (settings.stripe_secret_key or settings.demo_mode):
        health = "yellow"
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        health = "red"

    by_plan: dict[str, int] = {}
    for b in active:
        by_plan[b.plan] = by_plan.get(b.plan, 0) + 1

    return {
        "mrr_cad": mrr,
        "active_subscriptions": len(active),
        "total_brokerages": len(brokerages),
        "active_by_plan": by_plan,
        "system_health": health,
        "demo_mode": settings.demo_mode,
    }


@app.get("/brokerage/renewals")
def renewal_radar(brokerage_id: str, days: int = 90, db: Session = Depends(get_db)):
    """Policies expiring within N days, from already-extracted expiry_date."""
    from datetime import date, timedelta
    docs = db.query(Document).filter(Document.brokerage_id == brokerage_id).all()
    horizon, today, out = date.today() + timedelta(days=days), date.today(), []
    for d in docs:
        ej = d.extracted_json or {}
        exp = ej.get("expiry_date")
        try:
            expd = date.fromisoformat(str(exp)[:10])
        except (ValueError, TypeError):
            continue
        if today <= expd <= horizon:
            out.append({"document_id": d.id, "policy_number": ej.get("policy_number"),
                        "named_insured": ej.get("named_insured"), "expiry_date": str(expd),
                        "days_left": (expd - today).days, "status": d.status})
    out.sort(key=lambda r: r["days_left"])
    return {"renewals": out, "window_days": days}


@app.get("/healthz")
def healthz(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


# --- Feature routers (Brokerage Memory, Renewals, Compliance, Opportunities) ---
from features import router as features_router  # noqa: E402
app.include_router(features_router)
