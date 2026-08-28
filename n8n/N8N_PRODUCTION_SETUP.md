# True North — n8n Production Setup Guide

Five workflows live in your n8n cloud (`truenorthca.app.n8n.cloud`), built via MCP on 2026-07-06.
They are **drafts** — activate after the 3 setup steps below (activating earlier just produces failing runs).

| # | Workflow | ID | Trigger |
|---|----------|----|---------|
| 1 | TN 1 — Insurance Email Intake | `e3FmUD1Y8pml2h9U` | IMAP inbox |
| 2 | TN 2 — Document Processing Notification | `B5IuyZA7xy0PSsAH` | Webhook `POST /webhook/tn-doc-processed` |
| 3 | TN 3 — Renewal Radar | `muz5srNwyiV2uUTu` | Daily 08:00 |
| 4 | TN 4 — Compliance Monitoring | `1h4IFs6Iirspi0kF` | Weekly Mon 08:00 |
| 5 | TN 5 — AI Opportunity Detection | `Q2ZPlaKAFPzQfqyX` | Weekly Mon 09:00 |

## Setup (once, ~10 minutes)

### 1. Variables (Admin → Variables)
No secrets are hardcoded — every workflow reads these:

| Variable | Value |
|----------|-------|
| `API_BASE_URL` | your deployed backend, e.g. `https://truenorth-api.onrender.com` (⚠️ NOT localhost — n8n cloud can't reach your laptop) |
| `WEBHOOK_SECRET` | same value as the backend's `WEBHOOK_SHARED_SECRET` |
| `BROKERAGE_ID` | the tenant UUID, e.g. `00000000-0000-4000-8000-000000000001` |
| `BROKER_EMAIL` | where notifications/reports go |
| `FROM_EMAIL` | sender address matching your SMTP account |

### 2. Credentials (Credentials → Add)
- **`Brokerage Inbox IMAP`** (type IMAP) — the intake mailbox (host, port 993, SSL). For Gmail: app password; for M365: IMAP enabled + app password.
- **`True North SMTP`** (type SMTP) — sending account for notifications.
Open each workflow once; the placeholder credentials attach to the right nodes.

### 3. Activate
Toggle each workflow **Active**. TN 2's production URL becomes
`https://truenorthca.app.n8n.cloud/webhook/tn-doc-processed`.

## Customer onboarding (per brokerage)
1. Onboard via `POST /admin/brokerage` (x-admin-key) → note the returned UUID.
2. Duplicate TN 1 + TN 3 (or parameterize) with that brokerage's `BROKERAGE_ID` + their intake IMAP credential.
3. Customer completes Stripe checkout → status `active` → processing unblocked.
4. Forward a test PDF to the intake mailbox → confirm it appears in the portal.

## Security model
- Backend auth: `x-webhook-secret` header on `/webhook/document` and `/audit` (from `$vars`).
- No API keys/IDs hardcoded — all via n8n Variables + Credentials.
- Retry: HTTP nodes `maxTries 3`, 5s backoff; emails `maxTries 2`.
- Duplicates: backend SHA-256 dedup → 409 handled as a clean "skip" branch (no error).
- Failures: intake failures email the broker (`Notify Intake Failure`); the file stays in the inbox.
- AMF: no workflow ever emails a *client* — brokers get digests; client sends require portal approval.

## Test results (executed via MCP, 2026-07-06)
| Test | Execution | Result |
|------|-----------|--------|
| TN 3 digest: 3 tasks → 30/60/90 buckets, "expire dans 43 jours", overdue tag | #1 | ✅ |
| TN 2 routing: confidence 72 → *needs-review* branch (not approval) | #2 | ✅ |
| TN 4 compliance aggregation (missing VIN counted, bilingual report) | #3 | ✅ |
| TN 5 revenue report (8 100 $ total, per-client items) | #4 | ✅ |
| TN 1 failure path: HTTP 500 → failure notification branch | #5 | ✅ |

## Troubleshooting
- **HTTP node fails with `ECONNREFUSED/getaddrinfo`** → `API_BASE_URL` unset or points at localhost.
- **401 from backend** → `WEBHOOK_SECRET` doesn't match backend env.
- **IMAP trigger never fires** → credential wrong or mailbox has no *unseen* mail (it only reads UNSEEN).
- **Emails not sending** → SMTP credential; check FROM matches the authenticated account.
- **Duplicate notifications** → both TN 1 and TN 2 notify; disable TN 1's success email if you wire the backend to TN 2's webhook.
