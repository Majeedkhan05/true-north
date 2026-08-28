# Local Testing Guide — Brokerage-AI

Run and verify the entire system on your laptop with **no external accounts**
(no Stripe, no Gemini, no Supabase) using `DEMO_MODE=true`. Every status code in
the n8n contract is reproducible with plain `curl`.

---

## 0. One-time setup

```bash
cd brokerage-ai
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Create your env file
cp .env.example .env

# Generate a real JWT secret and put it in .env
python -c "import secrets; print('JWT_SECRET=' + secrets.token_urlsafe(48))"
#   -> copy the printed line over the JWT_SECRET line in .env
```

Confirm these lines in `.env` (defaults from `.env.example` already match):

```
DEMO_MODE=true
DATABASE_URL=sqlite:///./brokerage.db
WEBHOOK_SHARED_SECRET=local-dev-secret-change-me
JWT_SECRET=<the value you just generated>
```

> OCR libs (`tesseract`, `poppler`) are **not** needed in demo mode — the demo
> extractor returns structured data without reading the PDF bytes.

Optional helper for the commands below (nice JSON + id capture):

```bash
# macOS:  brew install jq
jq --version
```

---

## 1. Start the two processes

**Terminal 1 — API**
```bash
cd brokerage-ai && source .venv/bin/activate
uvicorn main:app --reload --port 8000
```

**Terminal 2 — Dashboard (optional UI)**
```bash
cd brokerage-ai && source .venv/bin/activate
API_BASE_URL=http://localhost:8000 streamlit run dashboard.py
# -> http://localhost:8501  (language selector is the first screen)
```

**Terminal 3 — curl tests.** Set shared vars:
```bash
BASE=http://localhost:8000
SECRET='x-webhook-secret: local-dev-secret-change-me'
```

Quick health check:
```bash
curl -s $BASE/healthz
# {"status":"ok"}
```

---

## 2. Create test brokerages

**(a) Active brokerage** (Ontario → English). Onboard, then activate via demo checkout.

```bash
ACME=$(curl -s -X POST $BASE/admin/brokerage \
  -H 'content-type: application/json' \
  -d '{"name":"ACME Brokers","email":"acme@demo.ca","postal_code":"M5H 2N2","plan":"starter"}' \
  | jq -r .id)
echo "ACME id = $ACME"

# Activate the subscription (demo mode flips status -> active instantly)
curl -s -X POST $BASE/billing/checkout \
  -F "brokerage_id=$ACME" -F "plan=starter" | jq .
# {"checkout_url":"http://localhost:8501?checkout=demo_success&plan=starter"}
```

**(b) Inactive brokerage** (Quebec → French) — onboard but DO NOT check out.

```bash
QC=$(curl -s -X POST $BASE/admin/brokerage \
  -H 'content-type: application/json' \
  -d '{"name":"Cabinet Tremblay","email":"qc@demo.ca","postal_code":"H3B 4W5","plan":"starter"}' \
  | jq -r .id)
echo "QC id = $QC   (status stays 'inactive')"
```

> Verify the bilingual default: ACME (M… = Ontario) → `"language":"en"`,
> QC (H… = Quebec) → `"language":"fr"`. Check with:
> `curl -s $BASE/admin/brokerages | jq '.[] | {name,language,status}'`

---

## 3. Reproduce every status code with curl

A tiny dummy PDF is enough (demo extractor doesn't parse it):
```bash
printf '%%PDF-1.4 demo policy INT-2024-0001' > /tmp/policy.pdf
```

### ✅ 200 — SUCCESS  (active brokerage, valid PDF)
```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST $BASE/webhook/document \
  -H "$SECRET" -F "brokerage_id=$ACME" -F "file=@/tmp/policy.pdf;type=application/pdf" | jq .
```
Expected body (abridged) — **HTTP 200**:
```json
{
  "status": "SUCCESS",
  "document_id": "….",
  "extracted_json": { "policy_number": "INT-2024-0001", "...": "..." },
  "confidence_score": 88.0,
  "draft_email": "Draft for review — …",
  "duplicate": false,
  "language": "en",
  "broker_email": "acme@demo.ca",
  "approval_token": "eyJhbGciOiJIUzI1Ni␣...␣"   // JWT — save this for §4
}
```

### ✅ 409 — DUPLICATE  (same bytes, same brokerage, run the §200 curl again)
```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST $BASE/webhook/document \
  -H "$SECRET" -F "brokerage_id=$ACME" -F "file=@/tmp/policy.pdf;type=application/pdf" | jq .
```
Expected — **HTTP 409**:
```json
{ "error": "DUPLICATE", "language": "en", "document_id": "…(original doc id)…" }
```

### ✅ 400 — INVALID_PDF  (non-PDF upload to active brokerage)
```bash
printf 'this is not a pdf' > /tmp/note.txt
curl -s -w '\nHTTP %{http_code}\n' -X POST $BASE/webhook/document \
  -H "$SECRET" -F "brokerage_id=$ACME" -F "file=@/tmp/note.txt;type=text/plain" | jq .
```
Expected — **HTTP 400**:
```json
{ "error": "INVALID_PDF", "language": "en", "broker_email": "acme@demo.ca" }
```

### ✅ 403 — SUBSCRIPTION_INACTIVE  (post to the inactive QC brokerage)
```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST $BASE/webhook/document \
  -H "$SECRET" -F "brokerage_id=$QC" -F "file=@/tmp/policy.pdf;type=application/pdf" | jq .
```
Expected — **HTTP 403** (note: French, because QC is a Quebec brokerage):
```json
{
  "error": "SUBSCRIPTION_INACTIVE",
  "language": "fr",
  "broker_email": "qc@demo.ca",
  "billing_portal_url": "https://billing.stripe.com/p/login/portal"
}
```

### ✅ 429 — QUOTA_EXCEEDED  (exhaust the active brokerage's quota)
There is no public endpoint to set usage, so push `docs_used` to the limit
directly (this is exactly what the app checks). Run from the project dir:
```bash
.venv/bin/python - <<'PY'
from database import SessionLocal
from models import Brokerage
db = SessionLocal()
b = db.query(Brokerage).filter(Brokerage.email == "acme@demo.ca").first()
b.docs_used = b.doc_limit          # starter limit = 100
db.commit()
print("docs_used =", b.docs_used, "/ doc_limit =", b.doc_limit)
db.close()
PY
```
Now post any **new** PDF (different bytes so it isn't a duplicate):
```bash
printf '%%PDF-1.4 another policy INT-2024-0002' > /tmp/policy2.pdf
curl -s -w '\nHTTP %{http_code}\n' -X POST $BASE/webhook/document \
  -H "$SECRET" -F "brokerage_id=$ACME" -F "file=@/tmp/policy2.pdf;type=application/pdf" | jq .
```
Expected — **HTTP 429**:
```json
{
  "error": "QUOTA_EXCEEDED",
  "language": "en",
  "broker_email": "acme@demo.ca",
  "upgrade_url": "https://app.brokerage-ai.ca/billing/upgrade"
}
```
> Reset afterwards by re-running the snippet with `b.docs_used = 0`.

### ✅ 500 — ERROR  (catch-all handler)
By design, every *known* failure is mapped to a 4xx, so you can't trigger 500
with normal input. To prove the global handler returns the contract string,
start a throwaway API pointed at an unreachable database and hit `/healthz`:
```bash
# separate terminal — does NOT touch your real server on :8000
DEMO_MODE=true DATABASE_URL='postgresql://no:no@127.0.0.1:1/none' \
  .venv/bin/uvicorn main:app --port 8009 &
sleep 2
curl -s -w '\nHTTP %{http_code}\n' http://localhost:8009/healthz
kill %1
```
Expected — **HTTP 500**:
```json
{ "error": "ERROR" }
```

---

## 4. Test `/approve/{token}` (JWT approval)

Grab a fresh token from a 200 response, then approve.

```bash
# Process a brand-new doc and capture its approval_token
printf '%%PDF-1.4 approve me INT-2024-0003' > /tmp/policy3.pdf
TOKEN=$(curl -s -X POST $BASE/webhook/document \
  -H "$SECRET" -F "brokerage_id=$ACME" -F "file=@/tmp/policy3.pdf;type=application/pdf" \
  | jq -r .approval_token)
echo "TOKEN = $TOKEN"
```
> If ACME is still at quota from §429, run the reset snippet (`docs_used = 0`) first.

### ✅ 200 — first click → approved
```bash
curl -s -w '\nHTTP %{http_code}\n' $BASE/approve/$TOKEN | jq .
```
```json
{ "status": "approved", "document_id": "…", "language": "en" }
```

### ✅ 200 — second click → already_approved (idempotent double-approval guard)
```bash
curl -s -w '\nHTTP %{http_code}\n' $BASE/approve/$TOKEN | jq .
```
```json
{ "status": "already_approved", "document_id": "…", "language": "en" }
```

### ✅ 401 — invalid token
```bash
curl -s -w '\nHTTP %{http_code}\n' $BASE/approve/not-a-real-token | jq .
```
```json
{ "detail": "INVALID_TOKEN" }
```

### ✅ 401 — expired token
```bash
.venv/bin/python - <<'PY'
import jwt
from config import settings
print(jwt.encode(
    {"document_id":"x","brokerage_id":"y","scope":"approve","exp":1000000000},
    settings.jwt_secret, algorithm=settings.jwt_algorithm))
PY
# copy the printed token:
curl -s -w '\nHTTP %{http_code}\n' $BASE/approve/<PASTE_EXPIRED_TOKEN> | jq .
```
```json
{ "detail": "TOKEN_EXPIRED" }
```

---

## 5. Test `/retry/process`

Headers required: `x-webhook-secret` and `x-brokerage-id`. Body: `{"document_id": ...}`.

### ✅ 200 — re-process (idempotent on an already-processed doc)
```bash
DOC=$(curl -s "$BASE/brokerage/documents?brokerage_id=$ACME" | jq -r '.[0].id')
curl -s -w '\nHTTP %{http_code}\n' -X POST $BASE/retry/process \
  -H "$SECRET" -H "x-brokerage-id: $ACME" \
  -H 'content-type: application/json' \
  -d "{\"document_id\":\"$DOC\"}" | jq '{status,document_id,confidence_score}'
```
```json
{ "status": "SUCCESS", "document_id": "…", "confidence_score": 88.0 }
```

### ✅ 404 — document not found
```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST $BASE/retry/process \
  -H "$SECRET" -H "x-brokerage-id: $ACME" \
  -H 'content-type: application/json' \
  -d '{"document_id":"does-not-exist"}' | jq .
```
```json
{ "error": "DOCUMENT_NOT_FOUND" }
```

### ✅ 400 — max retries exceeded
Create a failed doc already at the retry ceiling (`retry_count >= 2`), then retry:
```bash
FID=$(.venv/bin/python - <<PY
from database import SessionLocal
from models import Document
db = SessionLocal()
d = Document(brokerage_id="$ACME", file_hash="failhash-local", status="failed",
            extracted_json={}, confidence_score=0.0, retry_count=2)
db.add(d); db.commit(); db.refresh(d); print(d.id); db.close()
PY
)
curl -s -w '\nHTTP %{http_code}\n' -X POST $BASE/retry/process \
  -H "$SECRET" -H "x-brokerage-id: $ACME" \
  -H 'content-type: application/json' \
  -d "{\"document_id\":\"$FID\"}" | jq .
```
Expected — **HTTP 400**:
```json
{ "error": "MAX_RETRIES_EXCEEDED", "document_id": "…", "retry_count": 2 }
```

---

## 6. Verify the n8n contract WITHOUT running n8n

n8n only *routes on the HTTP status code* returned by FastAPI — so if FastAPI
emits the right codes/bodies, the contract is satisfied regardless of n8n.

**(a) Automated — one command proves all of it.** The included end-to-end test
asserts every status code, both approval outcomes, both 401 variants, and the
retry 404/400 paths:
```bash
.venv/bin/python test_flow.py
# -> 40 lines of "PASS …" then "ALL CHECKS PASSED ✅"
```

**(b) Manual cross-check against the routing table.** Each curl status above maps
1:1 to an n8n action in [`n8n/routing_table.json`](n8n/routing_table.json):

| FastAPI returns | Body marker | n8n action (routing_table.json) |
|-----------------|-------------|---------------------------------|
| 200 | `status: SUCCESS` | send draft email to broker |
| 429 | `error: QUOTA_EXCEEDED` | send upgrade email (`upgrade_url`) |
| 403 | `error: SUBSCRIPTION_INACTIVE` | send billing email (`billing_portal_url`) |
| 400 | `error: INVALID_PDF` | notify sender "PDF only" |
| 409 | `error: DUPLICATE` | stop silently |
| 500 | `error: ERROR` | retry 2× / 60s → alert admin |

| Approval (`/approve/{token}`) | Body | n8n approval_flow state |
|-------------------------------|------|--------------------------|
| 200 | `status: approved` | render "approved" page |
| 200 | `status: already_approved` | render "already approved" page |
| 401 | `detail: INVALID_TOKEN` / `TOKEN_EXPIRED` | render "invalid link" page |

If the curl outputs in §3–§5 match the "Expected" blocks, the FastAPI ↔ n8n
contract is fully satisfied. The n8n JSON in `n8n/` keys purely off these codes,
so importing it later requires no FastAPI changes.

---

## 7. Cleanup

```bash
rm -f brokerage.db brokerage_test.db
rm -rf local_storage __pycache__
```
