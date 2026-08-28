# Brokerage-AI — User Journeys

End-to-end flows tying screens ([`WIREFRAMES.md`](WIREFRAMES.md)), roles, system
events and endpoints together. Each step: **Screen → user action → system →
result**. Tenant is always session-resolved (no dropdowns); RLS scopes all data.

Personas: **Marie** (Owner, Cabinet Tremblay, Québec/FR) · **Jean** (Broker) ·
**Sara** (Reviewer) · **Alex** (Brokerage-AI super_admin).

---

## J1. Acquisition → first approved document (Québec, French-first)
```
Home(/) ─(Book a Demo, FR)─► /demo ─submit─► sales/Stripe trial provisioned
   │                                            (server derives language='fr'
   │                                             from QC postal → FR-first)
   ▼
Invite email (FR) ─▸ /invite/:token ─set password─► session{active_brokerage_id,
   role:Owner, lang:fr} ─► lands on /app **in French by default** (no toggle needed)
   ▼
/app Dashboard(FR): empty state « Aucun document — transférez une police à votre
   boîte de réception intake+<id>@… »
   ▼
Email arrives ─► n8n FLOW1 ─► POST /webhook/document ─► doc appears in queue
   ▼
/app/queue ─[Réviser]─► /review ─(fix franchise field, Enregistrer)─► PATCH doc
   ▼
/email ─(Approuver → confirm modal ☑ courtier autorisé)─► POST /brokerage/approve
   ▼
n8n FLOW2 sends client email (FR) ─► audit logged ─► toast « Approuvé ».
RESULT: first value in minutes, entirely in French, broker accountable (AMF).
```

## J2. Daily review loop (the core paying workflow)
```
Login ─► /app Dashboard ─[Réviser le suivant]─► /review (lowest-confidence first)
  loop:
    PDF ↔ fields, click value → source highlight, correct flagged (<85%) fields
    [Enregistrer] → PATCH ; [Régénérer] draft if fields changed
    /email → [Approuver] → confirm → POST /approve → auto-advance to next in queue
  exit when queue empty → empty state « Tout est à jour ✓ »
Keyboard: ⌘K to jump, J/K next/prev, A approve (with confirm). Optimistic UI;
queue badge decrements live (TanStack Query invalidate).
```

## J3. Low-confidence / failure handling
```
Queue shows ⚠ conf 72% ─► /review ─► Sara (Reviewer) can edit but [Approuver] is
  disabled ─[Signaler révision senior]─► assigned to Jean (Broker) ─► Jean approves.
Failed doc (500 upstream) ─► row ●échec retry 1/2 ─[Réessayer]─► POST /retry/process
  → resolves, or after 2 tries → admin alert (n8n FLOW4); user sees « En échec —
  support avisé ». No PII shown in any error.
```

## J4. Quota hit → upgrade (Stripe-gated)
```
Usage pill 100/100 ─► next email → backend 429 QUOTA_EXCEEDED
  ─► client maps to banner « Quota atteint » + [Mettre à niveau]
  ─► /app/billing/upgrade ─[Choisir PRO]─► POST /billing/checkout → Stripe Checkout
  ─► return /app/billing?checkout=success ─► /stripe/webhook updates plan+doc_limit
  ─► processing unblocks; usage meter resets cap. FR invoice issued (TPS/TVQ).
RESULT: self-serve expansion; no support ticket needed.
```

## J5. Subscription lapse → reactivate
```
invoice.payment_failed ─► /stripe/webhook sets status=past_due
  ─► every /app screen shows red banner « Paiement en retard »
  ─► new docs blocked (403 SUBSCRIPTION_INACTIVE) with [Réactiver]
  ─► /app/billing ─[Gérer le paiement]─► Stripe portal → card fixed
  ─► webhook → status=active → banner clears, processing resumes.
```

## J6. Team growth (roles & least privilege)
```
/app/team ─[Inviter]─► email + rôle(Reviewer) + langue ─► POST /invites (FR email)
  ─► Sara accepts /invite/:token ─► joins ONLY Cabinet Tremblay (RLS), role Reviewer
  ─► Sara sees queue + review, but cannot approve or open Billing/Team/Admin.
Owner later [Changer rôle → Broker] → Sara gains approve. Activity tab logs all
(actor, action, document_id, ts, IP masked) for AMF/Loi 25 accountability.
```

## J7. Multi-brokerage principal (the only place a switcher exists)
```
A group principal belongs to 2 cabinets ─► account menu ▾ shows a scoped switcher
  listing ONLY her 2 memberships (never a customer directory).
  Switch → active_brokerage_id swaps → x-brokerage-id changes → full refetch →
  RLS now scopes to the other tenant. URL/data never cross tenants.
```

## J8. Language-first experience & persistence (Loi 96)
```
QC brokerage → app boots in FR (brokerage.language='fr'). UI, emails, drafts,
  invoices all FR by default.
User flips topbar [EN] → me.language='en' persisted server-side + localStorage
  ─► UI switches to English on every device/login; BUT outbound client docs/emails
     & invoices stay FR (governed by brokerage.language) unless brokerage changes it
     in Settings → Cabinet. "Langue de service" recorded. fr-CA formatting throughout.
```

## J9. Super-admin support (customers never see this)
```
Alex logs in with STAFF identity ─► only /admin/* surface (AdminLayout).
  /admin Revenue (MRR/churn) ─► /admin/customers ─► open Cabinet Tremblay
  ─► [Impersonate] (requires consent flag, fully audited, banner shown)
  ─► reproduces issue ─► /admin/tickets reply (FR) ─► resolve.
GUARANTEE: no link to /admin anywhere in the customer portal; a customer hitting
  /admin/* receives 404 (no existence disclosure); staff auth ≠ customer auth.
```

---

## Cross-cutting state rules (apply to every journey)
- **Loading** → skeletons; **Empty** → illustration + primary action (FR/EN);
  **Error** → retry + localized message; **No-permission** → element hidden, route → 404.
- **Optimistic** approve/assign with rollback on failure.
- **Idempotent** approve (409 already_approved → silent success).
- **Never** render PII in lists/logs/errors below role permission (mirrors `pii_utils`).
- **Tenant** is server-authoritative on every request; cross-tenant access → 404.
