# 🍁 Brokerage-AI

Bilingual (EN/FR) AI document-processing SaaS for Canadian insurance brokerages: email → PDF → AI extraction → validated draft → broker approval, gated by Stripe billing.

**Status:** ✅ MVP ready · **58/58 end-to-end checks passing**

```bash
python test_flow.py     # -> 58 PASS, 0 FAIL, "ALL CHECKS PASSED"
```

Runs fully offline in `DEMO_MODE` (Stripe, Gemini and Supabase are stubbed), so the
whole pipeline is reproducible from a clean clone with no external accounts.

```
Email → n8n → FastAPI → Gemini 2.5 Flash → Validation → Draft Email → Streamlit → Stripe gate → Broker approval
```

## Tech stack

- **Backend:** FastAPI (Python 3.11+)
- **Frontend:** Streamlit (client portal + admin panel)
- **Database:** PostgreSQL / Supabase (`ca-central-1`) with Row Level Security; SQLite for local demo
- **AI:** Google Gemini 2.5 Flash
- **Payments:** Stripe (subscriptions + webhooks)
- **Orchestration:** n8n (email intake, routing, retries)
- **OCR / PDF:** pdfplumber + pytesseract
- **Auth:** PyJWT (signed approval tokens)

## Run locally (offline, no external accounts)

```bash
cd brokerage-ai
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env                                    # DEMO_MODE=true by default
python -c "import secrets; print(secrets.token_urlsafe(48))"   # paste into JWT_SECRET

uvicorn main:app --reload --port 8000                   # terminal 1 — API
streamlit run dashboard.py                              # terminal 2 — UI (http://localhost:8501)
```

`DEMO_MODE=true` stubs Stripe/Gemini/Supabase so the full pipeline runs end-to-end on SQLite. Full curl tests for every status code: see **[LOCAL_TESTING.md](LOCAL_TESTING.md)**.

## Deploy (summary)

1. Run `schema.sql` against Supabase Postgres (enables RLS + 90-day retention).
2. Set production `.env`: real `DATABASE_URL`, `GEMINI_API_KEY`, Stripe keys + price IDs, Supabase storage, `DEMO_MODE=false`.
3. Serve `main:app` (uvicorn/gunicorn) and `dashboard.py` behind a reverse proxy with TLS.
4. Import `n8n/*.json` workflows; point the IMAP intake at FastAPI.
5. Schedule `cron_cleanup.py` daily (document retention).

Detailed steps in **[deploy.md](deploy.md)**. Cloud/infra hardening comes later.

## File structure

```
brokerage-ai/
├── main.py                 # FastAPI app — all endpoints + status-code contract
├── models.py               # SQLAlchemy models + Pydantic schemas
├── database.py             # Engine/session (Postgres or SQLite)
├── config.py               # Env-driven settings + plan catalogue
├── auth.py                 # JWT approval tokens
├── gemini_client.py        # Gemini extraction (+ demo stub)
├── validation.py           # Policy-number / date / numeric validation
├── pii_utils.py            # PII masking + stripping
├── email_draft.py          # Bilingual draft email builder
├── stripe_integration.py   # Checkout, webhooks, subscription gating
├── storage.py              # Supabase storage + PDF text/OCR
├── i18n.py                 # EN/FR strings + Quebec-postal-code language rule
├── dashboard.py            # Streamlit client portal + admin panel
├── cron_cleanup.py         # 90-day document retention job
├── prompt.txt              # Gemini extraction prompt
├── schema.sql              # Postgres schema + RLS policies
├── requirements.txt
├── .env.example            # All vars, tagged [LOCAL]/[PROD]/[OPT]
├── test_flow.py            # End-to-end smoke test (40 checks)
├── LOCAL_TESTING.md        # Step-by-step local test guide
├── deploy.md               # Deployment guide
└── n8n/                    # Control-plane workflows + contract
    ├── email_ingestion.json    routing_table.json
    ├── approval_flow.json      webhook_schemas.json
    ├── billing_flow.json       retry_failure_logic.json
    └── failure_flow.json
```

## Status codes (FastAPI ↔ n8n contract)

`200 SUCCESS` · `429 QUOTA_EXCEEDED` · `403 SUBSCRIPTION_INACTIVE` · `400 INVALID_PDF` · `409 DUPLICATE` · `500 ERROR`

---

_Legal baseline (MVP, in code): broker approval required before client contact (AMF) · CASL footer (address + unsubscribe) · Quebec French by postal code · 90-day retention · audit logging._
