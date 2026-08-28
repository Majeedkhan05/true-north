# Brokerage-AI — Product Specification & Frontend Architecture

> Scope: **product + frontend only.** The FastAPI backend, Stripe gating, Gemini
> pipeline, Supabase/RLS, n8n orchestration and bilingual/Bill-96 legal baseline
> already exist. This document designs the **customer-facing product** that wraps
> them and the **React + Tailwind** app that replaces the Streamlit prototype.
>
> Companion docs: [`WIREFRAMES.md`](WIREFRAMES.md) (per-screen ASCII layouts) ·
> [`USER_JOURNEYS.md`](USER_JOURNEYS.md) (end-to-end flows). Folder structure + API
> map live in §8 of this file.

---

## 0.0 Non-negotiable requirements (hard constraints)

These govern every screen below. They are product-defining, not optional.

1. **No brokerage dropdowns — ever.** The tenant is resolved from the
   **authenticated session**, never chosen from a global list. A user is a member of
   exactly one brokerage (multi-brokerage staff get a *scoped* switcher limited to
   *their* memberships, not a directory). The active `brokerage_id` rides in the
   session/JWT; `lib/api/client.ts` attaches it as `x-brokerage-id` automatically.
   The portal UI never renders a list of other tenants. *(Replaces the Streamlit
   `st.selectbox("Select brokerage")` prototype entirely.)*
2. **Tenant isolation via RLS (defense in depth).** The server sets
   `app.brokerage_id` per request and Postgres RLS scopes every row; the frontend
   treats tenant as **server-authoritative** and never trusts a client-supplied id.
   Any cross-tenant URL (e.g. `/app/documents/:id` for a foreign doc) returns
   **404**, not 403 — no existence disclosure.
3. **Customers never see admin.** `/admin/*` is a **separate app surface**
   (`AdminLayout`), gated by the `super_admin` role server-side *and* by a route
   guard. There is **no link** to `/admin` anywhere in the brokerage portal, and a
   non-staff user hitting `/admin/*` gets a **404** (not a redirect that reveals the
   route). Staff auth is a distinct identity from customer auth.
4. **Quebec French-first.** For a brokerage whose `language='fr'` (already derived
   from postal code server-side), French is the **default and primary** language of
   the entire experience — UI, emails, drafts, invoices — not a toggle-to-reach
   afterthought. English is opt-in.
5. **Persistent language preference.** Stored server-side per **user**
   (`me.language`, governs UI) and per **brokerage** (`brokerage.language`, governs
   outbound documents/emails/invoices), with a `localStorage` fallback so the choice
   survives logout/login and new devices.
6. **French invoices & emails.** All billing artifacts and system/transactional
   emails have authoritative FR variants (TPS/TVQ labels, `fr-CA` currency
   `1 999,00 $ CAD`, FR legal footer); selected by brokerage language.

### 0.1 Auth & tenant model (replaces the dropdown)

```
Customer identity                         Staff identity (separate)
─────────────────                         ────────────────────────
login(email,pw) ─► session {              login(staff)  ─► session {
  user_id, name, lang,                       staff_id, role: super_admin
  memberships: [{ brokerage_id, role }]    }
  active_brokerage_id                      → only /admin/* surface
}
   │
   ▼
PortalLayout reads active_brokerage_id ─► every API call carries
x-brokerage-id (+ Authorization) ─► backend SET app.brokerage_id ─► RLS.
```
- **Single-brokerage user (the norm):** no switcher shown; tenant is implicit.
- **Multi-brokerage user (e.g. a group principal):** a compact switcher in the
  account menu lists **only their own** memberships; switching swaps
  `active_brokerage_id` and refetches. This is *not* a directory of all customers.
- **Guards:** `<RequireAuth>`, `<RequireRole>`, `<RequirePlanActive>` (mirrors the
  403/429 gates), `<RequireStaff>` for `/admin/*`.

---

## 0. Gap analysis — current Streamlit UI vs. a sellable product

**What exists today (`dashboard.py`):** a mandatory language gate, a Client Portal
(brokerage selector, document list, JSON viewer, draft-email preview, Approve,
billing checkout) and an Admin Panel (onboarding form, MRR, active subscriptions,
system-health light). It talks to: `/admin/brokerage[s]`, `/admin/metrics`,
`/webhook/document`, `/brokerage/documents`, `/brokerage/document/{id}`,
`/brokerage/approve/{id}`, `/check-duplicate`, `/audit`, `/approve/{token}`,
`/retry/process`, `/billing/checkout`, `/stripe/webhook`.

**Why no brokerage would pay for it yet — missing before GA:**

| Area | Missing |
|------|---------|
| Trust / acquisition | No marketing site, pricing, security page, demo booking, FAQ |
| Identity | No real auth, login, password reset, invite acceptance, session, SSO path |
| Multi-tenant UX | Brokerage chosen from a dropdown (not from the logged-in user) — unacceptable for prod |
| Core workflow | No field-level **extraction review**, no editable **draft email**, no confidence triage, no queue with **search/filters/pagination**, no document statuses beyond raw JSON |
| Billing self-serve | No usage meter, plan page, upgrade/downgrade, invoice history, payment methods |
| Team | No invite, roles/permissions, per-user activity |
| Admin depth | No customer management, support tickets, churn/revenue analytics, audit drill-down |
| Notifications | No in-app notifications, no email-preference center |
| Quebec/Bill 96 | Language is a session toggle, not a persisted French-**first** experience; no French invoices/receipts surfaced; no language-of-service controls |
| Quality bar | No empty/loading/error states, no mobile/responsive, no accessibility, no onboarding |

**Roles (RBAC) introduced by this spec:**
`Owner` (full + billing), `Admin` (team + all docs), `Broker` (review/approve own + team docs), `Reviewer` (review, cannot approve), `Read-only` (view + export). Plus internal `Platform Admin` (Brokerage-AI staff, separate app surface).

---

## 1. Information architecture

```
Public (unauthenticated)
  /                     Landing
  /features             Features
  /pricing              Pricing
  /security             Security & Compliance
  /faq                  FAQ
  /contact              Contact
  /demo                 Book a Demo
  /login  /forgot  /invite/:token   Auth

Brokerage Portal (authenticated, tenant-scoped)
  /app                  Dashboard
  /app/queue            Document Queue (search/filter)
  /app/documents/:id    Document Details
  /app/documents/:id/review   AI Extraction Review
  /app/documents/:id/email    Draft Email Review
  /app/notifications    Notifications
  /app/billing          Plan + Usage
  /app/billing/upgrade  Upgrade
  /app/billing/invoices Invoices
  /app/billing/payment  Payment Methods
  /app/team             Members / Roles
  /app/team/invite      Invite User
  /app/team/activity    Activity History
  /app/settings         Profile / Brokerage / Language

Platform Admin (Brokerage-AI staff only)
  /admin                Revenue Dashboard
  /admin/customers      Customer Management
  /admin/customers/:id  Customer Detail
  /admin/tickets        Support Tickets
  /admin/health         System Health
```

**Global shells:** `MarketingLayout` (public), `PortalLayout` (sidebar + topbar,
tenant context, language), `AdminLayout` (staff), `AuthLayout` (centered card).

**Persistent globals (every authenticated screen):** language toggle (FR/EN,
persisted per user **and** per brokerage), tenant badge, usage pill (docs used /
limit), notifications bell, account menu.

---

## 2. Public Marketing Website

> Goal: convert a Canadian brokerage principal in EN or FR. Bilingual, fast,
> compliance-forward. Reuses design tokens in §9.

### 2.1 Landing — `/`
- **Purpose:** Communicate value (email → AI extraction → broker-approved draft) and drive *Book a Demo* / *Start Free Trial*.
- **Components:** Hero (headline, sub, dual CTA, product mock/loop), trust bar (carrier logos: Desjardins, Intact, Belairdirect, TD, Co-operators), 3-step "How it works", outcome metrics (hours saved, accuracy), bilingual proof ("Conçu pour le Québec"), testimonial, security strip (PIPEDA/Law 25/AMF badges), pricing teaser, footer.
- **Buttons:** `Book a Demo`, `See Pricing`, `Sign in`, `FR/EN` toggle.
- **Data:** static + plan teaser from `config/plans.ts`.
- **Actions:** navigate, toggle language, submit email for trial.
- **Nav flow:** → /demo, /pricing, /features, /security, /login.

### 2.2 Features — `/features`
- **Purpose:** Detail capabilities for an evaluator.
- **Components:** Feature blocks (Email ingestion via n8n, OCR + Gemini extraction, confidence scoring, broker-in-the-loop approval, bilingual drafts, audit & 90-day retention, dedup, Stripe-gated access), per-feature screenshot, comparison vs. manual process.
- **Buttons:** `Book a Demo`, `View Security`, section anchors.
- **Data:** static.
- **Actions:** scroll, anchor nav, CTA.
- **Nav flow:** → /demo, /security, /pricing.

### 2.3 Pricing — `/pricing`
- **Purpose:** Present Starter $499/100, Pro $1,999/500, Enterprise $4,999/unlimited (CAD/mo) and convert.
- **Components:** 3 plan cards (price, doc quota, feature checklist, CTA), monthly/annual toggle, CAD currency + tax note, feature comparison table, FAQ accordion, "Talk to sales" for Enterprise.
- **Buttons:** `Start [Plan]`, `Contact Sales`, `Book a Demo`, billing-period toggle.
- **Data:** `config/plans.ts` (mirrors backend `PLANS`).
- **Actions:** select plan → /demo or /login→checkout; toggle period.
- **Nav flow:** → /demo, /login.

### 2.4 Contact — `/contact`
- **Purpose:** General inquiries.
- **Components:** Form (name, brokerage, email, phone, province, message, language-of-service preference), office address (CASL physical address), email/phone, map.
- **Buttons:** `Send message`, `Book a Demo instead`.
- **Data:** static; POST to `contact` intake (assumed `POST /public/contact`).
- **Actions:** submit (validated, reCAPTCHA), success toast.
- **Nav flow:** → /demo.

### 2.5 FAQ — `/faq`
- **Purpose:** Remove objections (security, accuracy, AMF/Bill 96, data residency, cancellation).
- **Components:** Searchable accordion grouped by Product / Security / Billing / Compliance; bilingual.
- **Buttons:** category filter, `Still have questions? Contact`.
- **Data:** static content (i18n).
- **Actions:** search, expand, deep-link to question.
- **Nav flow:** → /contact, /security.

### 2.6 Security & Compliance — `/security`
- **Purpose:** Pass procurement/compliance review.
- **Components:** Data residency (Supabase ca-central-1 / Montréal), encryption in transit/at rest, RLS multi-tenant isolation, PII handling (SIN/phone/address never sent to AI), 90-day auto-deletion, audit logging, AMF (broker approval before client contact), CASL (unsubscribe + address), **Québec Law 25 / Bill 96** statements, subprocessor list, breach policy, downloadable one-pager.
- **Buttons:** `Download security overview (PDF)`, `Request DPA`, `Contact security`.
- **Data:** static + PDF asset.
- **Actions:** download, request DPA.
- **Nav flow:** → /contact, /demo.

### 2.7 Book a Demo — `/demo`
- **Purpose:** Primary B2B conversion.
- **Components:** Two-step form (brokerage profile → scheduling), embedded calendar, qualifying fields (province, monthly doc volume, current process, preferred language), confirmation.
- **Buttons:** `Request demo`, slot select, `Add to calendar`.
- **Data:** POST `public/demo-request` (assumed); calendar embed.
- **Actions:** submit, pick slot, receive bilingual confirmation email.
- **Nav flow:** → confirmation → /.

---

## 3. Brokerage Portal

> Shell: `PortalLayout` — left sidebar (Dashboard, Queue, Notifications, Billing,
> Team, Settings), topbar (tenant name, usage pill, language toggle, bell,
> account menu). All data tenant-scoped via session → `x-brokerage-id`.

### 3.1 Dashboard — `/app`
- **Purpose:** At-a-glance operational state on login.
- **Components:** KPI cards (Pending review, Approved today, Avg confidence, Docs used/limit), usage meter, "Needs attention" list (low-confidence + failed), recent activity feed, quick actions, subscription banner (active/past_due/inactive).
- **Buttons:** `Review next`, `Go to Queue`, `Upgrade` (if near limit), per-item `Open`.
- **Data:** derived from `GET /brokerage/documents` + `GET /admin/metrics`-style tenant stats (assumed `GET /brokerage/stats`); plan/usage from brokerage object.
- **Actions:** open document, jump to queue, dismiss banner, upgrade.
- **Nav flow:** → /app/queue, /app/documents/:id, /app/billing/upgrade.

### 3.2 Document Queue — `/app/queue`
- **Purpose:** Triage and process the incoming pipeline.
- **Components:** Toolbar (search, filters, sort, bulk-select), filter chips (Status: processed/approved/failed; Confidence: ≥85 / <85; Date range; Policy type; Carrier; Assignee), table (checkbox, policy #, named insured *(masked per role)*, type, confidence meter, status badge, received, assignee, actions), pagination, empty/loading/error states, saved views.
- **Buttons:** `Open`, `Approve` (inline, if permitted), `Reassign`, `Export CSV`, `Retry` (failed), bulk `Approve`/`Assign`, `Clear filters`.
- **Data:** `GET /brokerage/documents` (extend with query params: `?status=&min_confidence=&q=&page=&assignee=`), confidence + status from doc model.
- **Actions:** search, filter, sort, paginate, select, bulk approve/assign, retry (→ `/retry/process`), export.
- **Nav flow:** row → /app/documents/:id; `Review` → /app/documents/:id/review.

### 3.3 Document Details — `/app/documents/:id`
- **Purpose:** Single source of truth for one document.
- **Components:** Header (policy #, status badge, confidence, received, assignee), 2-pane: left = **PDF/source preview** (Supabase signed URL), right = tabs [Extracted data · Draft email · Activity/Audit · Metadata]; side panel (file hash, retry_count, language, carrier); legal note "Draft for review by licensed broker".
- **Buttons:** `Review extraction`, `Review draft email`, `Approve`, `Reassign`, `Download PDF`, `Retry` (failed), `Copy JSON`.
- **Data:** `GET /brokerage/document/{id}` (extracted_json, confidence_score, status, draft_email, file_path, retry_count, created_at) + audit via `GET /brokerage/document/{id}/audit` (assumed).
- **Actions:** open review/email, approve, reassign, download, retry.
- **Nav flow:** → /review, /email; back → /app/queue.

### 3.4 AI Extraction Review — `/app/documents/:id/review`
- **Purpose:** Human-in-the-loop correction of Gemini output (accuracy + AMF accountability).
- **Components:** Split view PDF ↔ **editable field list**; per field (policy_number, named_insured, policy_type, coverage_limits, deductibles, effective_date, expiry_date, endorsements, action_items): value input, **confidence chip**, source-highlight on PDF, "needs review" flag for low confidence, validation hints (policy regex, date, numeric — mirrors `validation.py`), action-items checklist; overall confidence header; unsaved-changes guard.
- **Buttons:** `Save changes`, `Mark verified`, `Flag for senior review`, `Regenerate draft`, `Approve & continue`, field-level `Reset to AI value`.
- **Data:** `GET /brokerage/document/{id}`; saves via `PATCH /brokerage/document/{id}` (assumed) — frontend sends corrected `extracted_json`.
- **Actions:** edit fields, fix validation errors, save, verify, regenerate draft → /email.
- **Nav flow:** → /email; back → /documents/:id.

### 3.5 Draft Email Review — `/app/documents/:id/email`
- **Purpose:** Review/edit the bilingual draft before broker approval (never auto-sent — AMF).
- **Components:** Rich-text/plain editor with the generated draft, language indicator (FR/EN matches brokerage), required legal footer preview (CASL address + unsubscribe + "Draft for review"), recipient field (broker; client optional), variables/snippets, version history, side preview.
- **Buttons:** `Save draft`, `Regenerate`, `Approve` (locks + triggers downstream send via n8n FLOW 2), `Switch language`, `Insert template`.
- **Data:** `GET /brokerage/document/{id}` (draft_email, language, broker_email); approve via `POST /brokerage/approve/{id}`.
- **Actions:** edit, save, regenerate, approve (confirmation modal), language switch.
- **Nav flow:** Approve → success → /app/queue (next item).

### 3.6 Approval Workflow (cross-screen)
- **Purpose:** Enforce review → approve with double-approval guard + audit.
- **Components:** Approve confirmation modal (summary of key fields, confidence, "I confirm as licensed broker" checkbox), success state, idempotent guard (already-approved → 200 already_approved), role gate (Reviewer cannot approve).
- **Buttons:** `Confirm approval`, `Cancel`.
- **Data:** `POST /brokerage/approve/{id}` or token `GET /approve/{token}`; writes audit.
- **Actions:** confirm, handle 409 already-approved gracefully.
- **Nav flow:** any doc screen → modal → next-in-queue.

### 3.7 Search & Filters (component, used in Queue + global)
- **Purpose:** Find documents fast across a growing archive.
- **Components:** Global search (⌘K command palette: documents, settings, people), advanced filter drawer, saved/shared views, query chips, result counts.
- **Buttons:** `Apply`, `Save view`, `Share view`, `Reset`.
- **Data:** `GET /brokerage/documents` with params (assumed extension).
- **Actions:** type-ahead, filter, save, navigate to result.
- **Nav flow:** result → details.

### 3.8 Notifications — `/app/notifications`
- **Purpose:** Surface events needing action.
- **Components:** Bell with unread count, dropdown (recent), full page list grouped by type (New document, Low-confidence flagged, Approved, Failed/needs retry, Quota 80%/100%, Billing/payment, Team invite), per-item read/unread, preferences (in-app/email, per type, language).
- **Buttons:** `Mark all read`, per-item `Open` / `Dismiss`, `Notification settings`.
- **Data:** `GET /brokerage/notifications` (assumed); preferences `PATCH /me/preferences`.
- **Actions:** read, open target, configure channels.
- **Nav flow:** item → relevant doc/billing/team screen.

---

## 4. Billing Portal

> Stripe-gated. Self-serve plan, usage, invoices, payment methods. Owner/Admin only.

### 4.1 Current Plan — `/app/billing`
- **Purpose:** Show subscription state and entitlements.
- **Components:** Plan card (name, price CAD, renewal date, status badge active/trialing/past_due/canceled), entitlements list, usage meter (docs_used / doc_limit with reset date), past_due/inactive alert with reactivate CTA.
- **Buttons:** `Upgrade`, `Manage payment`, `View invoices`, `Cancel plan`, `Reactivate` (if inactive).
- **Data:** brokerage (`plan`, `status`, `doc_limit`, `docs_used`, `quota_period_start`); Stripe portal link.
- **Actions:** upgrade, open Stripe portal, cancel, reactivate.
- **Nav flow:** → /upgrade, /invoices, /payment.

### 4.2 Usage Meter — `/app/billing` (panel) / detail
- **Purpose:** Transparency on consumption to drive upgrades.
- **Components:** Big radial/bar (used vs limit), days left in cycle, trend sparkline (docs/day), projection ("on track to exceed by X"), per-user breakdown, overage policy note.
- **Buttons:** `Upgrade now`, `Export usage CSV`.
- **Data:** `GET /brokerage/usage` (assumed: time series from documents) + brokerage quota fields.
- **Actions:** view, export, upgrade.
- **Nav flow:** → /upgrade.

### 4.3 Upgrade — `/app/billing/upgrade`
- **Purpose:** Change plan via Stripe Checkout.
- **Components:** Plan comparison (current highlighted), proration note, CAD + tax, confirmation; mirrors `STRIPE_PRICE_*`.
- **Buttons:** `Choose [Plan]` → Checkout, `Talk to sales` (Enterprise), `Cancel`.
- **Data:** `POST /billing/checkout {plan}` → `{checkout_url}` → Stripe; result via `/stripe/webhook` updates plan/limit.
- **Actions:** select plan, redirect to Stripe, return success/cancel.
- **Nav flow:** → Stripe → /app/billing?checkout=success.

### 4.4 Invoice History — `/app/billing/invoices`
- **Purpose:** Self-serve receipts (FR/EN — see §6).
- **Components:** Table (invoice #, date, amount CAD, taxes GST/QST, status paid/open/failed, period), download PDF, language column, search/date filter.
- **Buttons:** `Download PDF`, `Download all`, `Open in Stripe`, filter.
- **Data:** `GET /billing/invoices` (assumed; backs onto Stripe).
- **Actions:** download (localized), filter, open Stripe receipt.
- **Nav flow:** standalone.

### 4.5 Payment Methods — `/app/billing/payment`
- **Purpose:** Manage cards / billing contact.
- **Components:** Saved cards (brand, last4, exp, default), add-card (Stripe Elements), billing address, billing email, tax IDs (GST/QST), Stripe Customer Portal embed/link.
- **Buttons:** `Add card`, `Set default`, `Remove`, `Edit billing info`, `Open Stripe portal`.
- **Data:** Stripe (via portal/SetupIntent); `stripe_customer_id` on brokerage.
- **Actions:** add/remove/default card, edit billing.
- **Nav flow:** standalone.

---

## 5. Team Management

> Owner/Admin manage members; RBAC from §0. Multi-tenant scoped.

### 5.1 Members / Roles — `/app/team`
- **Purpose:** See and manage who can access the brokerage.
- **Components:** Members table (name, email, role badge, status active/invited/suspended, last active, language), role selector, seat usage, permission matrix reference.
- **Buttons:** `Invite user`, per-row `Change role`, `Suspend`, `Remove`, `Resend invite`.
- **Data:** `GET /brokerage/members` (assumed); roles enum.
- **Actions:** change role, suspend/remove, resend invite.
- **Nav flow:** → /team/invite, /team/activity.

### 5.2 Invite User — `/app/team/invite`
- **Purpose:** Add a teammate with a role.
- **Components:** Form (email, role, default language, optional message), pending-invites list, seat-limit guard, bilingual invite email preview.
- **Buttons:** `Send invite`, `Cancel`, `Revoke invite`.
- **Data:** `POST /brokerage/invites` (assumed); acceptance via `/invite/:token`.
- **Actions:** send, revoke, copy link.
- **Nav flow:** → /team.

### 5.3 Activity History — `/app/team/activity`
- **Purpose:** Per-user audit (accountability; AMF/Law 25).
- **Components:** Timeline/table (actor, action, target document_id, timestamp, IP — **PII-masked per `pii_utils`**), filters (user, action, date), export.
- **Buttons:** `Export`, filter, `Open target`.
- **Data:** `GET /brokerage/audit` (from `audit_logs`, masked).
- **Actions:** filter, export, drill to document.
- **Nav flow:** item → /app/documents/:id.

---

## 6. Quebec / Bill 96 Requirements (cross-cutting)

**French-first UX**
- App **defaults to French** when brokerage `language='fr'` (Quebec postal → FR is already derived server-side). French is the *primary* language of the interface, emails, drafts, and invoices for Québec brokerages — not an afterthought toggle.
- All copy authored in **natural Canadian French** (not literal translation); FR strings are the source of truth for QC tenants.

**Persistent language toggle**
- Toggle in topbar + settings; persisted **per user** (`me.language`) and **per brokerage** (`brokerage.language`). User pref overrides for UI; brokerage pref governs outbound docs/emails/invoices. Survives reload/login (stored server-side + `localStorage` fallback). `i18next` with `en`/`fr` resource bundles.

**French invoices**
- Invoices/receipts for QC tenants rendered in French with FR tax labels (TPS/TVQ), FR legal entity name, and FR currency formatting (e.g., `1 999,00 $ CAD`). Both-language download option.

**French email templates**
- All system + draft emails (approval, billing, invites, notifications) have FR variants; selected by brokerage language. Legal footer (CASL address + unsubscribe + "Brouillon à réviser par un courtier autorisé") localized.

**Bill 96 considerations**
- Default language of service = French for Québec; English available on explicit user choice.
- Contract/ToS, invoices and customer communications available in French *at least as prominently* as English.
- Date/number/currency localization (`fr-CA`), `lang="fr"` on QC sessions for a11y.
- "Langue de service" preference captured at signup and in Settings; respected across all touchpoints.
- Avoid anglicisms in product copy; maintain a FR glossary (assuré désigné, avenant, prime, franchise, date d'entrée en vigueur, date d'échéance).

**Implementation:** `lib/i18n/{en.json,fr.json}`, `useLang()` hook, `<LangToggle/>`, `Intl` formatters in `utils/format.ts` keyed off active locale, server persistence via `PATCH /me/preferences` and brokerage settings.

---

## 7. Admin Portal (Brokerage-AI staff)

> Separate surface (`AdminLayout`), staff-auth + Platform-Admin role. Not tenant-scoped.

### 7.1 Revenue Dashboard — `/admin`
- **Purpose:** Business health for the operator.
- **Components:** MRR/ARR cards, MRR-by-plan bar, active subscriptions, trial→paid conversion, churn, new vs. churned, ARPA, system-health light.
- **Buttons:** date range, `Export`, drill to plan/customer.
- **Data:** `GET /admin/metrics` (mrr_cad, active_subscriptions, active_by_plan, system_health) + extensions (churn/trend assumed).
- **Actions:** filter range, export, drill down.
- **Nav flow:** → /admin/customers.

### 7.2 Customer Management — `/admin/customers` / `/admin/customers/:id`
- **Purpose:** Manage brokerage accounts and support them.
- **Components:** List (name, email, plan, status, MRR, docs_used/limit, created, province/language); detail (profile, subscription, usage trend, document volume, team, audit, impersonate-for-support with consent, manual plan/status override).
- **Buttons:** `View`, `Suspend`/`Reactivate`, `Change plan`, `Reset quota`, `Impersonate`, `Open Stripe`, `Export`.
- **Data:** `GET /admin/brokerages`, `POST /admin/brokerage` (onboard), per-customer detail (assumed `GET /admin/brokerages/:id`).
- **Actions:** onboard, edit plan/status, impersonate (audited), export.
- **Nav flow:** list → detail → tickets.

### 7.3 Support Tickets — `/admin/tickets`
- **Purpose:** Triage customer issues.
- **Components:** Ticket list (subject, brokerage, priority, status open/pending/closed, assignee, SLA timer), detail thread, internal notes, link to customer/document.
- **Buttons:** `Assign`, `Reply`, `Change status/priority`, `Link document`, `Close`.
- **Data:** `GET/POST /admin/tickets` (assumed).
- **Actions:** assign, reply, resolve, link entities.
- **Nav flow:** ticket → customer/document.

### 7.4 System Health — `/admin/health`
- **Purpose:** Operational monitoring.
- **Components:** Service lights (API, DB, Gemini, Stripe, n8n, Supabase storage) green/yellow/red, recent failures (failed docs, retries, 5xx), webhook delivery status, queue depth, latency, 90-day purge cron status.
- **Buttons:** `Refresh`, `View failed documents`, `Re-run purge`, `Open logs`.
- **Data:** `GET /admin/metrics` (system_health), `GET /healthz`, failures from documents/audit (assumed).
- **Actions:** refresh, drill into failures, trigger maintenance.
- **Nav flow:** → /admin/customers.

---

## 8. React + Tailwind Frontend Architecture

**Stack:** Vite + React 19 + TypeScript · Tailwind CSS + **shadcn/ui** (Radix
primitives) · React Router v6 · **TanStack Query** (server state) · Zustand (light
UI state) · **i18next** (EN/FR) · `@stripe/stripe-js` + Elements · `react-hook-form`
+ Zod (validation mirroring `validation.py`) · Recharts (admin/usage) ·
`@tanstack/react-table` (queues) · date-fns (`fr-CA`/`en-CA`).

### 8.1 Folder structure
```
brokerage-ai-web/
├─ index.html
├─ vite.config.ts
├─ tailwind.config.ts        # design tokens (§9)
├─ .env                      # VITE_API_URL, VITE_STRIPE_PK
└─ src/
   ├─ main.tsx               # providers: Query, Router, i18n, Auth, Stripe
   ├─ App.tsx
   ├─ routes.tsx             # route tree + guards + layouts
   ├─ config/
   │  ├─ plans.ts            # mirrors backend PLANS (Starter/Pro/Enterprise)
   │  ├─ nav.ts              # sidebar/marketing nav, role-gated
   │  └─ env.ts
   ├─ types/
   │  └─ models.ts           # Brokerage, Document, AuditLog, Member, Invoice... (mirror Pydantic)
   ├─ lib/
   │  ├─ api/
   │  │  ├─ client.ts        # fetch wrapper: base URL, auth header, x-brokerage-id, error→toast
   │  │  ├─ documents.ts     # list/get/patch/approve/retry  (hooks)
   │  │  ├─ brokerages.ts    # me, stats, usage, settings
   │  │  ├─ billing.ts       # checkout, invoices, payment, usage
   │  │  ├─ team.ts          # members, invites, roles
   │  │  ├─ audit.ts         # activity/notifications
   │  │  └─ admin.ts         # metrics, customers, tickets, health
   │  ├─ auth/
   │  │  ├─ AuthProvider.tsx # session, tenant, role, login/logout
   │  │  ├─ useAuth.ts
   │  │  └─ guards.tsx       # <RequireAuth/>, <RequireRole/>, <RequirePlanActive/>
   │  ├─ i18n/
   │  │  ├─ index.ts         # i18next init, locale persistence
   │  │  ├─ en.json  fr.json # FR is source of truth for QC
   │  │  └─ useLang.ts       # toggle + persist (user + brokerage)
   │  ├─ stripe.ts           # Stripe.js loader + redirectToCheckout
   │  ├─ query.ts            # QueryClient + keys factory
   │  └─ utils/
   │     ├─ format.ts        # Intl money (CAD, fr-CA "1 999,00 $"), dates, numbers
   │     ├─ confidence.ts    # 85 threshold helpers, color scale
   │     ├─ pii.ts           # client-side masking for display per role
   │     └─ validation.ts    # Zod schemas: policy #, dates, numerics
   ├─ components/
   │  ├─ ui/                 # shadcn: Button, Input, Select, Badge, Card, Table,
   │  │                      #   Dialog, Drawer, Tabs, Tooltip, Toast, Skeleton,
   │  │                      #   Pagination, Command(⌘K), Avatar, Switch, Progress
   │  ├─ layout/
   │  │  ├─ PortalShell.tsx  Sidebar.tsx  Topbar.tsx
   │  │  ├─ MarketingNav.tsx  Footer.tsx
   │  │  ├─ LangToggle.tsx  TenantBadge.tsx  UsagePill.tsx  NotificationBell.tsx
   │  │  └─ EmptyState.tsx  ErrorState.tsx  PageHeader.tsx
   │  └─ domain/
   │     ├─ DocumentTable.tsx  DocumentRow.tsx  StatusBadge.tsx
   │     ├─ ConfidenceMeter.tsx  ExtractionField.tsx  PdfPreview.tsx
   │     ├─ DraftEmailEditor.tsx  ApprovalModal.tsx  AuditTimeline.tsx
   │     ├─ UsageMeter.tsx  PlanCard.tsx  InvoiceRow.tsx
   │     ├─ MemberRow.tsx  RoleBadge.tsx  InviteForm.tsx
   │     └─ admin/ MrrChart.tsx CustomerRow.tsx TicketRow.tsx HealthLight.tsx
   ├─ layouts/
   │  ├─ MarketingLayout.tsx  AuthLayout.tsx  PortalLayout.tsx  AdminLayout.tsx
   ├─ pages/
   │  ├─ marketing/ Landing Features Pricing Contact Faq Security BookDemo
   │  ├─ auth/      Login Forgot AcceptInvite
   │  ├─ portal/    Dashboard Queue DocumentDetails ExtractionReview DraftReview Notifications Settings
   │  ├─ billing/   Plan Usage Upgrade Invoices PaymentMethods
   │  ├─ team/      Members InviteUser ActivityHistory
   │  └─ admin/     Revenue Customers CustomerDetail Tickets SystemHealth
   └─ styles/
      ├─ globals.css         # Tailwind base + tokens
      └─ tokens.css
```

### 8.2 Pages → routes → guards (summary)
- Public pages under `MarketingLayout`; `/login,/forgot,/invite/:token` under `AuthLayout`.
- `/app/*` under `PortalLayout` wrapped by `<RequireAuth>` + tenant context; billing pages add `<RequireRole roles={['owner','admin']}>`; approval actions gated by `<RequirePlanActive>` (mirrors 403) and `<RequireRole>` (Reviewer can't approve).
- `/admin/*` under `AdminLayout` with `<RequireRole roles={['platform_admin']}>`.

### 8.3 Layouts
- **MarketingLayout:** sticky nav (logo, links, FR/EN, `Book a Demo`), footer (CASL address, FR/EN, legal links).
- **AuthLayout:** centered card, language toggle, brand.
- **PortalLayout:** collapsible `Sidebar` (role-gated `nav.ts`), `Topbar` (TenantBadge, UsagePill, LangToggle, NotificationBell, account menu), `<Outlet/>`, global ⌘K `Command`, toast region, subscription banner.
- **AdminLayout:** staff sidebar (Revenue, Customers, Tickets, Health), impersonation banner when active.

### 8.4 API integration map (frontend → existing/assumed endpoints)
| Hook / module | Method · Endpoint | Status |
|---|---|---|
| `useDocuments(filters)` | `GET /brokerage/documents?status&min_confidence&q&page&assignee` | exists (extend query params) |
| `useDocument(id)` | `GET /brokerage/document/{id}` | exists |
| `useSaveExtraction(id)` | `PATCH /brokerage/document/{id}` | **assumed (frontend contract)** |
| `useApprove(id)` | `POST /brokerage/approve/{id}` | exists |
| `useApproveToken(token)` | `GET /approve/{token}` | exists |
| `useRetry(id)` | `POST /retry/process` | exists |
| `useDedupCheck()` | `POST /check-duplicate` | exists |
| `useAuditLog(id)` | `GET /brokerage/document/{id}/audit` | assumed |
| `useTenant()/useStats()` | `GET /brokerage/me`, `GET /brokerage/stats` | assumed |
| `useUsage()` | `GET /brokerage/usage` | assumed |
| `useCheckout(plan)` | `POST /billing/checkout` → Stripe | exists |
| `useInvoices()` | `GET /billing/invoices` | assumed (Stripe-backed) |
| `usePaymentPortal()` | Stripe Customer Portal link | assumed |
| `useMembers()/useInvite()` | `GET/POST /brokerage/members`,`/invites` | assumed |
| `useNotifications()` | `GET /brokerage/notifications` | assumed |
| `usePreferences()` | `PATCH /me/preferences` (language, channels) | assumed |
| `useAdminMetrics()` | `GET /admin/metrics` | exists |
| `useCustomers()` | `GET /admin/brokerages`, `GET /admin/brokerages/:id` | exists / extend |
| `useOnboard()` | `POST /admin/brokerage` | exists |
| `useTickets()` | `GET/POST /admin/tickets` | assumed |
| `useHealth()` | `GET /healthz`, `GET /admin/metrics` | exists |

> Endpoints marked **assumed** are the API contracts the frontend expects; they are
> documented here as integration points only — **no backend is designed in this spec.**

**Client conventions:** `lib/api/client.ts` injects `Authorization` (session) and
`x-brokerage-id` (active tenant) on every call, maps the backend's structured error
bodies (`{error:"SUBSCRIPTION_INACTIVE"|"QUOTA_EXCEEDED"|...}`) to localized toasts,
and routes `403`→reactivate banner, `429`→upgrade prompt, `409`→"already processed",
matching the existing status-code contract. TanStack Query handles caching,
optimistic approve, and background refetch of the queue.

---

## 9. Design system (tokens & states)

- **Palette (light, premium, trust):** ink `#14110F`, surface `#FFFFFF`, canvas
  `#F7F5F1`, primary/maple `#C8102E` (Canada red, used sparingly for accents/CTAs),
  success `#2E7D5B`, warn `#B7791F`, danger `#B00C20`, hairline `rgba(20,17,15,.10)`.
- **Confidence scale:** ≥85 success-green chip, 70–84 warn-amber, <70 danger.
- **Type:** UI `Inter`; display/marketing `Playfair Display` (reuse marketing brand).
- **Required states for every data screen:** loading (Skeleton), empty (illustration +
  primary action), error (retry), and **no-permission** (role-gated) — all bilingual.
- **A11y:** WCAG 2.1 AA, focus rings, `lang` attribute per locale, keyboard ⌘K,
  44px targets, contrast ≥ 4.5:1 (never text below `#888` on white).
- **Responsive:** sidebar collapses to drawer < 1024px; tables → stacked cards < 768px.

---

## 10. Build phasing (so it ships)

1. **P0 — Sellable core:** Auth + tenant, PortalLayout, Dashboard, Queue
   (search/filter/paginate), Document Details, **Extraction Review**, **Draft Review +
   Approval**, Billing (Plan/Usage/Upgrade), French-first i18n. *(This is the minimum a
   brokerage pays for.)*
2. **P1 — Self-serve + trust:** Invoices, Payment Methods, Team (invite/roles/activity),
   Notifications, Marketing site (Landing/Pricing/Security/Demo), FR invoices/emails.
3. **P2 — Operate & scale:** Admin (Revenue/Customers/Tickets/Health), saved views, ⌘K,
   FAQ/Contact/Features, SSO, exports, advanced Bill-96 language-of-service controls.

---

*This document defines the product surface only. Backend, AI, billing logic and
orchestration are unchanged and are referenced as integration points.*
