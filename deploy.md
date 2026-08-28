# Brokerage-AI — Deployment Guide

Bilingual (EN/FR) AI insurance-document processing SaaS for Canadian brokerages.

```
Email → PDF → n8n → FastAPI → Gemini → Validation → Draft Email → Streamlit → Stripe gate → Broker approval
```

Single VPS (DigitalOcean **Toronto / tor1**), Supabase Postgres + Storage in
**Montreal / ca-central-1**.

---

## 0. Prerequisites

- Python 3.11+
- A Supabase project in **ca-central-1**
- Stripe account (test + live)
- Google AI Studio key for **Gemini 2.5 Flash**
- `tesseract-ocr` and `poppler-utils` for OCR fallback:
  ```bash
  # Ubuntu / DigitalOcean droplet
  sudo apt-get update && sudo apt-get install -y tesseract-ocr tesseract-ocr-fra poppler-utils
  # macOS
  brew install tesseract poppler
  ```
  (`tesseract-ocr-fra` adds the French OCR language pack.)

---

## 1. Local setup (runs fully offline)

```bash
cd brokerage-ai
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

To try the whole flow with **no external keys**, set in `.env`:

```
DEMO_MODE=true
DATABASE_URL=sqlite:///./brokerage.db
```

In demo mode: Stripe checkout marks the brokerage active immediately, Gemini
returns a deterministic structured extraction, and files are stored under
`./local_storage`. Everything else (validation, dedup, draft email, approval,
audit logs, RLS-equivalent filtering) runs for real.

Start both processes (two terminals):

```bash
# Terminal 1 — API
uvicorn main:app --reload --port 8000

# Terminal 2 — Dashboard
API_BASE_URL=http://localhost:8000 streamlit run dashboard.py
```

Open http://localhost:8501 →
1. Pick a language (mandatory first screen).
2. **Admin Panel** → onboard a brokerage (a Quebec postal code like `H3B 4W5`
   auto-selects French; an Ontario code like `M5H 2N2` selects English).
3. **Client Portal** → Billing → Subscribe (demo activates instantly).
4. Upload a policy PDF → see extracted JSON + bilingual draft email → Approve.

---

## 2. Database (Supabase, ca-central-1)

```bash
psql "$DATABASE_URL" -f schema.sql
```

This creates `brokerages`, `documents`, `audit_logs`, enables **Row Level
Security**, and installs the `purge_old_documents()` retention function. Each
request the API issues `SET app.brokerage_id = '<uuid>'` so RLS isolates every
brokerage to its own rows. The Supabase **service-role** key bypasses RLS for
admin/onboarding only.

Set `DATABASE_URL` to the Supabase URI (Settings → Database → Connection string).

---

## 3. Supabase Storage

Create a **private** bucket named `documents` (matches `SUPABASE_STORAGE_BUCKET`).
PDFs are stored at `<brokerage_id>/<sha256>.pdf`.

---

## 4. Stripe

1. Create three recurring prices (CAD/month): Starter $499, Pro $1999,
   Enterprise $4999. Put their price IDs in `.env`.
2. Add a webhook endpoint → `https://api.YOURDOMAIN/stripe/webhook`, events:
   `checkout.session.completed`, `customer.subscription.created`,
   `customer.subscription.updated`, `customer.subscription.deleted`,
   `invoice.payment_failed`. Copy the signing secret to `STRIPE_WEBHOOK_SECRET`.
3. The gate: `check_subscription_active()` blocks `/webhook/document` with **403**
   whenever status ∉ {active, trialing}.

Local webhook testing:
```bash
stripe listen --forward-to localhost:8000/stripe/webhook
```

---

## 5. Gemini

Set `GEMINI_API_KEY` and `GEMINI_MODEL=gemini-2.5-flash`. The system prompt is
`prompt.txt`; the brokerage's language is injected as `{{LANGUAGE}}`. PII
(SIN/phone/address) is stripped by `pii_utils.strip_for_ai()` **before** any call
to Gemini.

---

## 6. n8n (email ingestion only)

Import `n8n_workflow.json`. Set n8n env vars: `API_BASE_URL`,
`WEBHOOK_SHARED_SECRET`, `BROKER_NOTIFY_EMAIL`, `ADMIN_ALERT_EMAIL`.
Flow: IMAP trigger → extract PDF → SHA256 dedup → `POST /webhook/document` →
`200` send draft to broker · `403` send "subscription inactive" · `500` retry +
alert admin. Address convention `intake+<brokerage_id>@yourdomain` routes mail to
the right brokerage.

---

## 7. Production on the VPS (DigitalOcean Toronto)

```bash
# API (systemd unit example)
[Unit]
Description=brokerage-ai api
After=network.target
[Service]
WorkingDirectory=/opt/brokerage-ai
EnvironmentFile=/opt/brokerage-ai/.env
ExecStart=/opt/brokerage-ai/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
[Install]
WantedBy=multi-user.target
```

Run Streamlit similarly: `streamlit run dashboard.py --server.port 8501
--server.address 0.0.0.0`. Front both with nginx + TLS (Let's Encrypt).
`api.DOMAIN → :8000`, `app.DOMAIN → :8501`.

---

## 8. Retention cron (90-day auto-delete)

```cron
0 3 * * *  cd /opt/brokerage-ai && .venv/bin/python cron_cleanup.py >> /var/log/brokerage-purge.log 2>&1
```

Or use Supabase `pg_cron` (commented line at the bottom of `schema.sql`).
Documents older than 90 days are deleted (file + row); **audit logs are kept**.

---

## 9. Legal baseline (implemented in code)

- Every draft email contains **"Draft for review by licensed broker"** and is
  **never** sent to clients — broker approval is required (**AMF**).
- Emails include the company **physical mailing address** + **unsubscribe** link
  (**CASL**) — see `.env` `COMPANY_*` vars and `email_draft.py`.
- Quebec default language by postal code; full FR support across UI, emails, AI
  output, invoices (`i18n.py`).
- 90-day document auto-delete; audit logs always stored (`cron_cleanup.py`).

---

## 10. Health

`GET /healthz` (DB ping) and `GET /admin/metrics` (MRR, active subs,
green/yellow/red system health) back the Admin Panel's health indicator.
