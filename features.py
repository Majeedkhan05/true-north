"""
Brokerage Memory (search), AI Renewal Manager, Compliance Engine, Opportunity Engine.
Extends the existing pipeline — no existing endpoint is modified. All endpoints are
tenant-scoped by brokerage_id and reuse log_audit from main via late import.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Document, Brokerage, RenewalTask

router = APIRouter()

# ---------------------------------------------------------------- helpers
def _docs(db: Session, brokerage_id: str) -> list[Document]:
    return db.query(Document).filter(Document.brokerage_id == brokerage_id).all()

def _num(v: Any) -> float:
    """Parse '2 000 000 $' / '$2,000,000' / 2000000 → float."""
    if isinstance(v, (int, float)):
        return float(v)
    m = re.sub(r"[^\d.]", "", str(v or ""))
    try:
        return float(m) if m else 0.0
    except ValueError:
        return 0.0

def _max_liability(ej: dict) -> float:
    lims = ej.get("coverage_limits") or {}
    vals = [_num(v) for v in lims.values()] if isinstance(lims, dict) else []
    return max(vals) if vals else 0.0

def _date(s: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None

def _audit(db, **kw):
    from main import log_audit
    log_audit(db, **kw)

# ---------------------------------------------------------------- FEATURE 2: Brokerage Memory
@router.get("/brokerage/search")
def search_documents(
    brokerage_id: str,
    q: str = "",
    policy_type: str = "",
    status: str = "",
    min_liability: float = 0,
    expiring_before: str = "",
    endorsement: str = "",
    page: int = 1,
    page_size: int = 25,
    db: Session = Depends(get_db),
):
    """Full-text + structured search over the brokerage's extracted documents."""
    out = []
    exp_before = _date(expiring_before)
    needle = q.strip().lower()
    for d in _docs(db, brokerage_id):
        ej = d.extracted_json or {}
        if status and d.status != status:
            continue
        if policy_type and policy_type.lower() not in str(ej.get("policy_type", "")).lower():
            continue
        if min_liability and _max_liability(ej) < min_liability:
            continue
        if exp_before:
            ed = _date(ej.get("expiry_date"))
            if not ed or ed > exp_before:
                continue
        if endorsement:
            ends = " ".join(str(e) for e in (ej.get("endorsements") or []))
            if endorsement.lower() not in ends.lower():
                continue
        if needle:
            blob = " ".join([str(ej), str(d.draft_email or "")]).lower()
            if needle not in blob:
                continue
        out.append({
            "document_id": d.id, "policy_number": ej.get("policy_number"),
            "named_insured": ej.get("named_insured"), "policy_type": ej.get("policy_type"),
            "expiry_date": ej.get("expiry_date"), "max_liability": _max_liability(ej),
            "status": d.status, "confidence_score": d.confidence_score,
        })
    total = len(out)
    start = (max(page, 1) - 1) * page_size
    return {"total": total, "page": page, "page_size": page_size,
            "results": out[start:start + page_size]}

# ---------------------------------------------------------------- FEATURE 3: Renewal Manager
_RENEWAL_TMPL = {
    "en": ("Renewal reminder — policy {p}",
           "Hello,\n\nThe policy {p} for {n} expires on {e} ({days} days). "
           "We recommend beginning the renewal process now.\n\n"
           "— Draft for review by a licensed broker. Not sent to the client."),
    "fr": ("Rappel de renouvellement — police {p}",
           "Bonjour,\n\nLa police {p} de {n} arrive à échéance le {e} ({days} jours). "
           "Nous recommandons d'entamer le renouvellement dès maintenant.\n\n"
           "— Brouillon à réviser par un courtier autorisé. Non transmis au client."),
}

@router.post("/brokerage/renewals/generate")
def generate_renewal_tasks(brokerage_id: str, days: int = 90, db: Session = Depends(get_db)):
    """Create renewal tasks (with bilingual draft emails) for policies expiring within N days."""
    b = db.query(Brokerage).filter(Brokerage.id == brokerage_id).first()
    if not b:
        raise HTTPException(404, {"error": "BROKERAGE_NOT_FOUND"})
    lang = "fr" if (b.language or "en").startswith("fr") else "en"
    today, horizon, created = dt.date.today(), dt.date.today() + dt.timedelta(days=days), []
    for d in _docs(db, brokerage_id):
        ej = d.extracted_json or {}
        ed = _date(ej.get("expiry_date"))
        if not ed or not (today <= ed <= horizon):
            continue
        if db.query(RenewalTask).filter(RenewalTask.document_id == d.id,
                                        RenewalTask.status != "completed").first():
            continue  # idempotent: one open task per document
        subj, body = _RENEWAL_TMPL[lang]
        fmt = dict(p=ej.get("policy_number") or d.id[:8], n=ej.get("named_insured") or "—",
                   e=str(ed), days=(ed - today).days)
        t = RenewalTask(brokerage_id=brokerage_id, document_id=d.id,
                        policy_number=ej.get("policy_number"), named_insured=ej.get("named_insured"),
                        expiry_date=str(ed), language=lang,
                        draft_email=subj.format(**fmt) + "\n\n" + body.format(**fmt))
        db.add(t); created.append(t.policy_number or d.id[:8])
    db.commit()
    _audit(db, brokerage_id=brokerage_id, document_id=None,
           action=f"renewal_tasks_generated count={len(created)}", ip_address=None)
    return {"created": len(created), "policies": created}

@router.get("/brokerage/renewals/tasks")
def list_renewal_tasks(brokerage_id: str, status: str = "", db: Session = Depends(get_db)):
    q = db.query(RenewalTask).filter(RenewalTask.brokerage_id == brokerage_id)
    if status:
        q = q.filter(RenewalTask.status == status)
    tasks = q.all()
    today = dt.date.today()
    out = []
    for t in tasks:
        ed = _date(t.expiry_date)
        overdue = bool(ed and ed < today and t.status not in ("completed", "sent"))
        out.append({"id": t.id, "document_id": t.document_id, "policy_number": t.policy_number,
                    "named_insured": t.named_insured, "expiry_date": t.expiry_date,
                    "days_left": (ed - today).days if ed else None,
                    "status": "overdue" if overdue else t.status,
                    "language": t.language, "draft_email": t.draft_email})
    out.sort(key=lambda r: r["days_left"] if r["days_left"] is not None else 9999)
    return {"tasks": out}

@router.post("/brokerage/renewals/tasks/{task_id}/status")
def update_renewal_task(task_id: str, brokerage_id: str, new_status: str,
                        db: Session = Depends(get_db)):
    """Broker-controlled transitions. Emails are never sent automatically:
    'approved' only marks broker sign-off; sending is the broker's email client / n8n."""
    if new_status not in ("approved", "sent", "completed", "pending"):
        raise HTTPException(400, {"error": "INVALID_STATUS"})
    t = (db.query(RenewalTask)
         .filter(RenewalTask.id == task_id, RenewalTask.brokerage_id == brokerage_id).first())
    if not t:
        raise HTTPException(404, {"error": "TASK_NOT_FOUND"})
    t.status = new_status
    db.commit()
    _audit(db, brokerage_id=brokerage_id, document_id=t.document_id,
           action=f"renewal_task_{new_status}", ip_address=None)
    return {"id": t.id, "status": t.status}

# ---------------------------------------------------------------- FEATURE 4: Compliance Engine
_C_MSG = {
    "missing_insured":   ("Named insured is missing", "Le nom de l'assuré est manquant"),
    "missing_policy_no": ("Policy number is missing", "Le numéro de police est manquant"),
    "expired":           ("Policy is already expired", "La police est déjà expirée"),
    "bad_dates":         ("Effective date is after expiry date", "La date d'effet est postérieure à l'échéance"),
    "missing_dates":     ("Effective or expiry date missing/unreadable", "Date d'effet ou d'échéance manquante/illisible"),
    "no_coverage":       ("No coverage limits detected", "Aucune limite de couverture détectée"),
    "low_confidence":    ("Low extraction confidence — verify against source", "Confiance d'extraction faible — vérifier la source"),
    "missing_vin":       ("Auto policy without VIN", "Police automobile sans NIV"),
    "wrong_province":    ("Postal code province differs from brokerage", "La province du code postal diffère du cabinet"),
}

def run_compliance(doc: Document, brokerage: Brokerage | None) -> dict:
    ej = doc.extracted_json or {}
    flags: list[str] = []
    if not ej.get("named_insured"): flags.append("missing_insured")
    if not ej.get("policy_number"): flags.append("missing_policy_no")
    eff, exp = _date(ej.get("effective_date")), _date(ej.get("expiry_date"))
    if not eff or not exp: flags.append("missing_dates")
    elif eff > exp: flags.append("bad_dates")
    elif exp < dt.date.today(): flags.append("expired")
    if not (ej.get("coverage_limits") or {}): flags.append("no_coverage")
    if (doc.confidence_score or 0) < 70: flags.append("low_confidence")
    ptype = str(ej.get("policy_type", "")).lower()
    if ("auto" in ptype) and not (ej.get("vin") or ej.get("VIN")): flags.append("missing_vin")
    score = max(0, 100 - 18 * len(flags))
    return {"score": score,
            "risk": "high" if score < 50 else ("medium" if score < 82 else "low"),
            "flags": [{"code": f, "en": _C_MSG[f][0], "fr": _C_MSG[f][1]} for f in flags]}

@router.post("/brokerage/documents/{document_id}/validate")
def validate_document(document_id: str, brokerage_id: str, db: Session = Depends(get_db)):
    d = (db.query(Document)
         .filter(Document.id == document_id, Document.brokerage_id == brokerage_id).first())
    if not d:
        raise HTTPException(404, {"error": "DOCUMENT_NOT_FOUND"})
    b = db.query(Brokerage).filter(Brokerage.id == brokerage_id).first()
    d.compliance = run_compliance(d, b)
    d.opportunities = run_opportunities(d)
    db.commit()
    _audit(db, brokerage_id=brokerage_id, document_id=d.id,
           action=f"compliance_validated score={d.compliance['score']}", ip_address=None)
    return {"document_id": d.id, "compliance": d.compliance, "opportunities": d.opportunities}

# ---------------------------------------------------------------- FEATURE 5: Opportunity Engine
_O_RULES = [
    # (code, test(ej)->bool, revenue CAD/yr, en, fr)
    ("umbrella", lambda ej: _max_liability(ej) >= 1_000_000 and not any(
        "umbrella" in str(k).lower() or "parapluie" in str(k).lower()
        for k in (ej.get("coverage_limits") or {})), 900,
     "High liability without umbrella coverage — recommend an umbrella policy",
     "Responsabilité élevée sans protection parapluie — recommander une police parapluie"),
    ("cyber", lambda ej: "commercial" in str(ej.get("policy_type", "")).lower() and not any(
        "cyber" in str(k).lower() for k in (ej.get("coverage_limits") or {})), 1200,
     "Commercial client without cyber coverage — recommend cyber insurance",
     "Client commercial sans couverture cyber — recommander une assurance cyber"),
    ("low_liability", lambda ej: 0 < _max_liability(ej) < 1_000_000, 400,
     "Liability below 1M$ — recommend reviewing limits",
     "Responsabilité sous 1 M$ — recommander une révision des limites"),
    ("flood", lambda ej: any(t in str(ej.get("policy_type", "")).lower()
                             for t in ("habitation", "property", "commercial")) and not any(
        "flood" in str(e).lower() or "inondation" in str(e).lower()
        for e in (ej.get("endorsements") or [])), 350,
     "Property policy without flood endorsement — assess flood risk",
     "Police de biens sans avenant inondation — évaluer le risque d'inondation"),
]

def run_opportunities(doc: Document) -> dict:
    ej = doc.extracted_json or {}
    if not ej:
        return {"score": 0, "estimated_revenue_cad": 0, "items": []}
    items = [{"code": c, "en": en, "fr": fr, "estimated_revenue_cad": rev}
             for c, test, rev, en, fr in _O_RULES if test(ej)]
    return {"score": min(100, 25 * len(items)),
            "estimated_revenue_cad": sum(i["estimated_revenue_cad"] for i in items),
            "items": items}

@router.get("/brokerage/opportunities")
def list_opportunities(brokerage_id: str, db: Session = Depends(get_db)):
    """Aggregated, exportable opportunity report across the brokerage."""
    rows, total = [], 0.0
    for d in _docs(db, brokerage_id):
        opp = d.opportunities or run_opportunities(d)
        if opp["items"]:
            ej = d.extracted_json or {}
            rows.append({"document_id": d.id, "policy_number": ej.get("policy_number"),
                         "named_insured": ej.get("named_insured"), **opp})
            total += opp["estimated_revenue_cad"]
    rows.sort(key=lambda r: -r["estimated_revenue_cad"])
    return {"opportunities": rows, "total_estimated_revenue_cad": total}
