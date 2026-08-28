# Brokerage-AI — n8n Control Plane (Production)

n8n is the **orchestration brain**; FastAPI is the **source of truth**. n8n never
decides billing/dedup/extraction — it routes on what FastAPI returns and sends
email. No PII is ever stored in execution data or notifications.

Import these four workflows (Workflows → Import from File):

| File | Flow | Trigger |
|------|------|---------|
| `email_ingestion.json` | FLOW 1 — Email → PDF → AI → route | IMAP |
| `approval_flow.json`   | FLOW 2 — Broker approval → client email | Webhook `POST /webhook/approval-complete` |
| `billing_flow.json`    | FLOW 3 — Stripe → enforce subscription | Webhook `POST /webhook/stripe` |
| `failure_flow.json`    | FLOW 4 — Retry + admin alert | Error Trigger + Execute Workflow |

After importing, open **FLOW 4**, copy its workflow id, and set it as
`N8N_WF_FAILURE_FLOW_ID` (env) so flows 1–3 route global errors to it.

---

## 1. Environment variables (n8n → Settings → Variables, or container env)

| Variable | Required | Example | Used by |
|----------|----------|---------|---------|
| `FASTAPI_URL` | ✅ | `https://api.brokerage-ai.ca` | all FastAPI calls |
| `WEBHOOK_SHARED_SECRET` | ✅ | (same value as FastAPI `.env`) | auth header on every FastAPI call |
| `SUPABASE_URL` | ⚠️ optional | `https://xxx.supabase.co` | only if you enable a direct-upload node (off by default — see §6) |
| `SUPABASE_SERVICE_KEY` | ⚠️ optional | `eyJ...` | same as above |
| `STRIPE_SECRET_KEY` | ⚠️ optional | `sk_live_...` | only if you add Stripe API nodes; signature verify is done by FastAPI |
| `SYSTEM_FROM_EMAIL` | ✅ | `noreply@brokerage-ai.ca` | all outbound email |
| `BROKER_NOTIFY_EMAIL` | ✅ | `ops@brokerage.ca` | fallback broker recipient |
| `ADMIN_ALERT_EMAIL` | ✅ | `alerts@brokerage-ai.ca` | FLOW 4 admin alerts |
| `STRIPE_UPGRADE_URL` | ✅ | `https://app…/billing/upgrade` | 429 email |
| `STRIPE_PORTAL_URL` | ✅ | `https://billing.stripe.com/p/login/…` | 403 / billing emails |
| `N8N_WF_FAILURE_FLOW_ID` | ✅ | `Xy12…` | flows 1–3 `errorWorkflow` + explicit calls |

**Credentials (not env):** create an **IMAP** credential named `Brokerage IMAP`
and an **SMTP** credential for the Send Email nodes.

---

## 2. FLOW 1 — Email Ingestion (node by node)

1. **IMAP Trigger** (`emailReadImap`) — Mailbox `INBOX`, Format `resolved`,
   `customEmailConfig=["UNSEEN"]`, Download Attachments **on**, credential
   `Brokerage IMAP`. Address convention: brokers forward to
   `intake+<brokerage_id>@yourdomain` so the tenant is resolvable.
2. **Validate + SHA256** (Code) — picks the PDF binary; rejects non-PDF or
   `> 10 MB`; resolves `brokerage_id` from the `intake+<id>@` recipient; computes
   SHA-256. Emits only `{brokerage_id, file_hash, size, valid, reason}` — **no
   sender PII persisted**.
3. **IF Valid PDF** — true → continue; false → **Notify Sender – PDF Only**.
4. **POST /check-duplicate** (HTTP, `retryOnFail` 3×/60s) — body
   `{brokerage_id, file_hash}`, header `x-webhook-secret`. Cheap pre-check so we
   don't spend Gemini on a dup.
5. **IF Duplicate** — `body.duplicate === true` → **Audit: duplicate_skipped**
   then stop; else continue.
6. **POST /webhook/document** (HTTP, multipart, `retryOnFail` 3×/60s) — sends the
   binary as `file` + `brokerage_id`; headers `x-webhook-secret`,
   `x-brokerage-id`, `Idempotency-Key=<sha256>`. **Upload to Supabase happens
   server-side here** (single writer — see §6).
7. **Compute Route** (Code) — maps `(statusCode, confidence_score)` →
   `DRAFT | REVIEW | BILLING | UPGRADE | INVALID | DUPLICATE | ERROR`. Logs only
   `{document_id, status, confidence, code}`.
8. **Switch on Route** → one branch each:
   - `DRAFT` (200 & confidence **≥ 85**) → **Draft to Broker** (sends `draft_email`)
   - `REVIEW` (200 & confidence **< 85**) → **Review Required** (notification only — no draft body)
   - `BILLING` (403) → **Billing Reminder** (`billing_portal_url`)
   - `UPGRADE` (429) → **Upgrade Email** (`upgrade_url`)
   - `INVALID` (400) → notify
   - `DUPLICATE` (409) → stop silently
   - `ERROR` (500/other) → **Execute FLOW 4** with `{brokerage_id, document_id, context, attempt:0}`

> **IF conditions used:** `valid === true` (boolean), `body.duplicate === true`
> (boolean), and the route string equality in the Switch. Confidence threshold
> `85` lives in the Compute Route Code node (one place to change it).

---

## 3. FLOW 2 — Approval Pipeline (node by node)

Triggered by FastAPI **after** a broker approves (`/brokerage/approve/{id}` or
`/approve/{token}` → backend POSTs `N8N_APPROVAL_WEBHOOK_URL`).

1. **Webhook** `POST /webhook/approval-complete`, responseMode `responseNode`.
2. **Verify Secret + Extract** (Code) — rejects bad `x-webhook-secret` (→ error
   workflow); pulls `{brokerage_id, document_id, language, broker_email,
   client_email, final_email}`.
3. **IF client_email present** —
   - true → **Send Final Email to Client** (To `client_email`, CC `broker_email`).
   - false → **Send to Broker to Forward** (AMF-safe: broker forwards).
4. **Audit: final_email_sent** (HTTP `/audit`).
5. **200 OK** (Respond to Webhook).

All Send/HTTP nodes are `retryOnFail` 3×/60s.

---

## 4. FLOW 3 — Billing Enforcement (node by node)

1. **Webhook** `POST /webhook/stripe`, `rawBody=true` (point your Stripe webhook
   endpoint here).
2. **Forward raw → FastAPI `/stripe/webhook`** (HTTP, `retryOnFail` 3×/60s) —
   passes `Stripe-Signature` + raw body. FastAPI verifies the signature and
   **updates the DB** (activate / suspend / cancel). n8n makes no billing decision.
3. **200 ACK to Stripe** (Respond) — immediate.
4. **Classify Event** (Code) — `checkout.session.completed→ACTIVATE`,
   `invoice.payment_failed→SUSPEND`, `customer.subscription.deleted→BLOCK`, else
   `IGNORE`.
5. **Switch on Action** → **ACTIVATE / SUSPEND / BLOCK** notification emails (or
   IGNORE no-op). No PII beyond the brokerage's own contact email.

---

## 5. FLOW 4 — Failure Handling (node by node)

Two entry points converge on PII-safe alerts:

- **Error Trigger (global):** set as `errorWorkflow` on flows 1–3, so **any**
  node error anywhere lands here → **Build PII-safe Message**
  (`"Processing failed for brokerage_id X"` + workflow/node names only) →
  **Admin Alert** → **Audit (error)**.
- **Execute Workflow Trigger (retry):** called by FLOW 1 on `ERROR`. Loop:
  **Wait** (exp backoff `60·2^attempt`) → **POST /retry/process** → **Evaluate**
  → Switch `RESOLVED | RETRY_AGAIN | ALERT_ADMIN`. `RETRY_AGAIN` loops; after
  **2 retries** → **Admin Alert (retry exhausted)**.

Retry config: per-node `retryOnFail=true, maxTries=3 (=2 retries),
waitBetweenTries=60000` on all HTTP/email nodes **plus** this workflow-level
escalation. Idempotent: `/retry/process` no-ops on already-processed docs and
returns 400 after `retry_count ≥ 2`.

---

## 6. Design decisions (production-safe, per the hard rules)

- **Single uploader.** `/webhook/document` already uploads the PDF to Supabase
  Storage (keyed by `<brokerage_id>/<sha256>.pdf`, idempotent). Having n8n upload
  *as well* would double-write and race. So n8n streams the binary to FastAPI and
  the backend is the only writer. `SUPABASE_*` env vars are therefore optional and
  only needed if you deliberately add a direct-upload node.
- **FastAPI owns every decision** — dedup (409), subscription gate (403/429),
  extraction/confidence, Stripe state. n8n only routes + emails.
- **No PII anywhere in n8n.** Execution logs carry `{document_id, status,
  confidence}`; admin alerts say only `Processing failed for brokerage_id X`.
  `saveDataSuccessExecution=none` on all flows.
- **Idempotency.** SHA-256 pre-check + server-side dedup; approval guarded by
  `doc.status`; Stripe handled idempotently by FastAPI; `Idempotency-Key` header
  on the document POST.
- **Multi-tenant isolation.** `brokerage_id` flows through every header/payload;
  FastAPI applies Postgres RLS per request.

---

## 7. Status / contract quick reference

`/webhook/document` → `200 SUCCESS` (route on `confidence_score` ≥/< 85) ·
`429 QUOTA_EXCEEDED` · `403 SUBSCRIPTION_INACTIVE` · `400 INVALID_PDF` ·
`409 DUPLICATE` · `500 ERROR`. Full request/response payloads in
[`webhook_schemas.json`](webhook_schemas.json); status→action map in
[`routing_table.json`](routing_table.json).
