# Brokerage-AI — Wireframes

Low-fidelity ASCII layouts for every screen in [`PRODUCT_SPEC.md`](PRODUCT_SPEC.md).
Annotations: `[Button]` · `{data}` · `(action)` · `« FR-first »`. Tenant is always
from session — **no brokerage dropdown anywhere**.

Legend: `▸` link · `◉` active · `�(n)` count · `⌘K` command palette.

---

## A. PUBLIC SITE

### A1. Home `/`
```
┌──────────────────────────────────────────────────────────────────────┐
│  ◆ BROKERAGE-AI        Features  Pricing  Security      [FR|EN] [Login]│
├──────────────────────────────────────────────────────────────────────┤
│                                                                        │
│     Le courrier devient une police traitée.                           │
│     AI document processing for Canadian brokerages.                    │
│                                                                        │
│     [ Book a Demo ]   [ See Pricing ]                                  │
│                                                                        │
│     ┌──────────── product loop / screenshot ────────────┐             │
│     │  Email ▸ PDF ▸ AI extract ▸ Broker approves ▸ Sent │             │
│     └────────────────────────────────────────────────────┘            │
├──────────────────────────────────────────────────────────────────────┤
│  Trusted with:  Desjardins · Intact · Belairdirect · TD · Co-operators │
├──────────────────────────────────────────────────────────────────────┤
│  How it works   ① Ingest   ② Extract+score   ③ Broker approves         │
│  Outcomes       {12h saved/wk}  {98% list-to-sale}  {EN/FR native}     │
│  « Conçu pour le Québec » — Loi 25 · AMF · résidence des données QC    │
│  [ Security & compliance ]                       [ Book a Demo ]       │
├──────────────────────────────────────────────────────────────────────┤
│  Footer: address (CASL) · Privacy · Terms · Français · status         │
└──────────────────────────────────────────────────────────────────────┘
```

### A2. Features `/features`
```
┌─ nav ────────────────────────────────────────────────────────────────┐
│  Crafted without compromise                                           │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐                         │
│  │Email intake│ │OCR+Gemini  │ │Confidence  │  each: icon + 1-liner   │
│  │ via n8n    │ │ extraction │ │ scoring    │  + screenshot           │
│  └────────────┘ └────────────┘ └────────────┘                         │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐                         │
│  │Broker-in-  │ │Bilingual   │ │Audit + 90d │                         │
│  │the-loop    │ │ drafts     │ │ retention  │                         │
│  └────────────┘ └────────────┘ └────────────┘                         │
│  Manual vs Brokerage-AI  [comparison table]        [ Book a Demo ]    │
└──────────────────────────────────────────────────────────────────────┘
```

### A3. Pricing `/pricing`
```
┌─ nav ───────────────────────────────  [Monthly|Annual]  ─────────────┐
│  ┌──────────┐   ┌──────────┐◉popular   ┌──────────┐                   │
│  │ STARTER  │   │   PRO    │           │ENTERPRISE│                   │
│  │ $499/mo  │   │ $1,999/mo│           │ $4,999/mo│                   │
│  │ 100 docs │   │ 500 docs │           │ unlimited│                   │
│  │ ✓ ✓ ✓    │   │ ✓ ✓ ✓ ✓  │           │ ✓ all + SSO│                 │
│  │[Start]   │   │[Start]   │           │[Contact] │                   │
│  └──────────┘   └──────────┘           └──────────┘                   │
│  Prices in CAD · taxes (TPS/TVQ) extra                                │
│  [ Full feature comparison ▾ ]      FAQ accordion                     │
└──────────────────────────────────────────────────────────────────────┘
```

### A4. Security & Compliance `/security`
```
┌─ nav ────────────────────────────────────────────────────────────────┐
│  Built for Canadian compliance                                        │
│  • Data residency: Supabase ca-central-1 (Montréal)                   │
│  • Encryption in transit + at rest    • RLS tenant isolation          │
│  • PII never sent to AI (SIN/phone/address stripped)                  │
│  • 90-day auto-deletion   • Full audit log                            │
│  • AMF: broker approval before any client contact                     │
│  • Loi 25 / Bill 96 · CASL · subprocessors · breach policy           │
│  [ Download security overview PDF ]  [ Request DPA ]  [ Contact ]     │
└──────────────────────────────────────────────────────────────────────┘
```

### A5. Login `/login`   (AuthLayout — centered)
```
                ┌─────────────────────────────┐
                │   ◆ BROKERAGE-AI   [FR|EN]   │
                │   Connexion / Sign in        │
                │                              │
                │   Email    [______________]  │
                │   Password [______________]  │
                │            [   Se connecter ]│
                │   ▸ Mot de passe oublié ?    │
                │   ─────────  ou  ─────────   │
                │   [  SSO (Enterprise)  ]     │
                └─────────────────────────────┘
   On success → resolve session.active_brokerage_id → /app   (no dropdown)
   Invite link /invite/:token → set password → joins one brokerage + role
```

---

## B. BROKERAGE PORTAL  (PortalLayout)

### Shell (every /app screen)
```
┌────────┬─────────────────────────────────────────────────────────────┐
│SIDEBAR │ TOPBAR: {Brokerage name ◉ Québec}  [usage 62/100] [FR|EN] 🔔(3) ⌘K ▾me│
│        ├─────────────────────────────────────────────────────────────┤
│▸Tableau│                                                              │
│ de bord│              « page content (Outlet) »                       │
│▸Documents                                                            │
│▸File   │   subscription banner appears here if past_due/inactive      │
│▸Factura│                                                              │
│▸Équipe │                                                              │
│▸Réglages                                                            │
│        │   (NO link to /admin — customers never see it)               │
└────────┴─────────────────────────────────────────────────────────────┘
me ▾ : Profil · Préférences · (scoped brokerage switcher if multi) · Déconnexion
```

### B1. Dashboard `/app`
```
┌ PageHeader: Bonjour, Marie — {Cabinet Tremblay}  « FR-first »          ┐
│ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────────┐               │
│ │À réviser│ │Approuvés│ │Confiance│ │ Usage 62/100     │               │
│ │  ▸ 8    │ │ auj. 14 │ │ moy 91% │ │ ▓▓▓▓▓▓▓░░ reset 12j│             │
│ └─────────┘ └─────────┘ └─────────┘ └─────────────────┘               │
│ ┌ Needs attention ───────────────────────────────────────┐           │
│ │ ⚠ INT-2024-0481  conf 72%  faible confiance   [Réviser] │           │
│ │ ⚠ DOC failed     retry 1/2                     [Réessayer]│          │
│ └────────────────────────────────────────────────────────┘           │
│ Recent activity feed ……                          [ Réviser le suivant ]│
└────────────────────────────────────────────────────────────────────────┘
```

### B2. Documents / Review Queue `/app/queue`
```
┌ Toolbar: [🔍 search policy/insured]  Filtres: (Statut▾)(Conf▾)(Date▾)(Carrier▾)(Assigné▾) [Effacer] ┐
│         Saved views: ◉Tous  À réviser  <85%  Échecs           [Export CSV]│
├──────────────────────────────────────────────────────────────────────────┤
│ ☐ │ Police #     │ Assuré* │ Type   │ Confiance │ Statut  │ Reçu  │ ⋯    │
│ ☐ │ INT-2024-481 │ A•••• I │ Auto   │ ▇▇▇░ 72%  │ ●traité │ 2h    │[Open]│
│ ☐ │ TD-99-2231   │ L•••• B │ Habit. │ ▇▇▇▇ 94%  │ ●traité │ 3h    │[Open]│
│ ☐ │ DSJ-552      │ —       │ Comm.  │ ▇▇▇▇ 88%  │ ✓approuvé│ 1j   │[Open]│
├──────────────────────────────────────────────────────────────────────────┤
│ [☑ 2] bulk: [Approuver] [Assigner ▾]            ◄ 1 2 3 … ►  (page)       │
└──────────────────────────────────────────────────────────────────────────┘
*insured masked per role (pii_utils). Row click → B3. GET /brokerage/documents?…
```

### B3. Document Details `/app/documents/:id`
```
┌ INT-2024-0481  ●traité  conf 72%  reçu 2h  assigné: Marie    [Approuver]┐
├───────────────────────────────┬──────────────────────────────────────────┤
│  PDF / source preview         │ [Extraction][Courriel][Activité][Méta]   │
│  (Supabase signed URL)        │ ┌ Extraction (read) ──────────────────┐  │
│  ┌─────────────────────────┐  │ │ Police #     INT-2024-0481  ●72%    │  │
│  │                         │  │ │ Assuré       Acme Logistique inc.   │  │
│  │     [ page image ]      │  │ │ Type         Automobile             │  │
│  │                         │  │ │ En vigueur   2024-07-01             │  │
│  └─────────────────────────┘  │ │ Échéance     2025-07-01             │  │
│  ◄ pg 1/3 ►   [Télécharger]   │ │ Limites…  Franchises…  Avenants…    │  │
│                               │ └─────────────────────────────────────┘  │
│                               │ [Réviser l'extraction] [Réviser courriel]│
└───────────────────────────────┴──────────────────────────────────────────┘
GET /brokerage/document/{id}.  ⚠ "Brouillon à réviser par un courtier autorisé"
```

### B4. AI Extraction Review `/app/documents/:id/review`
```
┌ Réviser l'extraction — INT-2024-0481      conf globale 72% ⚠            ┐
├───────────────────────────────┬──────────────────────────────────────────┤
│  PDF  (click value → highlight │  Champs (éditables)                      │
│        source region)          │  Police #   [INT-2024-0481      ] ●72%   │
│  ┌─────────────────────────┐   │  Assuré     [Acme Logistique inc.] ●95%  │
│  │  ░░ highlighted ░░       │   │  Type       [Automobile  ▾]       ●88%  │
│  │                         │   │  En vigueur [2024-07-01 ]✓ valid  ●90%  │
│  │                         │   │  Échéance   [2025-07-01 ]✓        ●90%  │
│  └─────────────────────────┘   │  Franchise  [5 000 $    ]⚠ vérifier ●60%│
│                               │  Avenants   [+ add chip]                  │
│                               │  Action items ☑ renouveler 30j avant      │
│                               │  [Réinitialiser au champ IA] per-field    │
├───────────────────────────────┴──────────────────────────────────────────┤
│ [Enregistrer] [Marquer vérifié] [Signaler révision senior] [Régénérer ▸]  │
└────────────────────────────────────────────────────────────────────────────┘
PATCH /brokerage/document/{id}  (corrected extracted_json). Zod = validation.py
```

### B5. Draft Email Review + Approval `/app/documents/:id/email`
```
┌ Courriel provisoire — FR ◉   (langue = cabinet)                         ┐
├──────────────────────────────────────────┬─────────────────────────────┤
│ À: [courtier@cabinet.ca]  Client: (opt)  │  Aperçu                     │
│ Objet: [Document à réviser — INT-2024-481]│  ┌────────────────────────┐ │
│ ┌──────────────────────────────────────┐ │  │ Bonjour,               │ │
│ │ Bonjour,                             │ │  │ …key fields…           │ │
│ │ Un document d'assurance a été traité…│ │  │ ⚠ Brouillon à réviser  │ │
│ │ • Police: INT-2024-0481              │ │  │ par un courtier autorisé│ │
│ │ • Assuré: Acme Logistique inc.       │ │  │ [adresse CASL]         │ │
│ │ [Insérer modèle ▾]                   │ │  │ [se désabonner]        │ │
│ └──────────────────────────────────────┘ │  └────────────────────────┘ │
│ [Enregistrer] [Régénérer] [Changer langue]│  Versions ▾                 │
├──────────────────────────────────────────┴─────────────────────────────┤
│                                              [   Approuver   ]          │
└──────────────────────────────────────────────────────────────────────────┘
Approve → modal:
        ┌ Confirmer l'approbation ───────────────────┐
        │ Police INT-2024-0481 · conf 72%            │
        │ ☑ Je confirme à titre de courtier autorisé │
        │            [Annuler]   [Confirmer]         │
        └────────────────────────────────────────────┘
POST /brokerage/approve/{id} → n8n FLOW2 sends. 409 already_approved handled.
Reviewer role: [Approuver] hidden/disabled.
```

### B6. Billing `/app/billing`
```
┌ Facturation  (Owner/Admin only)                                        ┐
│ ┌ Forfait actuel ──────────────┐ ┌ Utilisation ───────────────────┐   │
│ │ PRO · 1 999 $/mois · ●actif  │ │ 62 / 500 documents             │   │
│ │ Renouvellement 2026-07-01    │ │ ▓▓▓░░░░░  réinit. dans 12 j     │   │
│ │ [Changer de forfait]         │ │ projection: 410 ce cycle       │   │
│ │ [Gérer le paiement]          │ │ [Exporter CSV]                 │   │
│ └──────────────────────────────┘ └────────────────────────────────┘   │
│ Tabs: [Forfait] [Factures] [Moyens de paiement]                        │
│ ─ Factures: # · date · montant CAD · TPS/TVQ · statut · [PDF FR ▾]     │
│ ─ Paiement: •••• 4242 défaut · [Ajouter carte] · [Portail Stripe]     │
└──────────────────────────────────────────────────────────────────────────┘
past_due/inactive → red banner [Réactiver] → POST /billing/checkout
```

### B7. Team `/app/team`
```
┌ Équipe  (Owner/Admin)                              [Inviter un membre]  ┐
│ Membre            Courriel          Rôle      Statut     Dernière activité│
│ Marie Tremblay    marie@…           Owner     ●actif     il y a 5 min     │
│ Jean Côté         jean@…            Broker    ●actif     hier             │
│ Sara L.           sara@…            Reviewer  ⧗invité    —      [Renvoyer]│
│ row ⋯ : Changer rôle ▾ · Suspendre · Retirer                            │
├──────────────────────────────────────────────────────────────────────────┤
│ Sièges: 3/10           Tabs: [Membres] [Activité]                        │
│ Activité: acteur · action · document_id · horodatage · IP(masquée)       │
└──────────────────────────────────────────────────────────────────────────┘
Invite modal: courriel · rôle ▾ · langue par défaut · message → POST /invites
```

### B8. Settings `/app/settings`
```
┌ Réglages          Tabs: [Profil] [Cabinet] [Langue] [Notifications]     ┐
│ Profil:   nom · courriel · mot de passe · langue d'interface (me.lang)   │
│ Cabinet:  raison sociale · code postal · langue des documents (broker)   │
│           ↳ « Langue de service par défaut : Français »  (Loi 96)        │
│ Langue:   ◉ Français   ○ English      [persisté · serveur + appareil]    │
│ Notif:    canaux in-app/courriel par type (nouveau doc, <85%, quota…)    │
└──────────────────────────────────────────────────────────────────────────┘
PATCH /me/preferences · brokerage settings.  Toggle persists across login.
```

---

## C. ADMIN PORTAL  (AdminLayout · super_admin only · /admin)

> Completely separate surface. No path from the customer portal. Non-staff → 404.

### C1. Revenue `/admin`
```
┌ ◆ ADMIN  Revenue  Customers  Tickets  Health         {staff} [Déconnexion]┐
│ ┌ MRR ─────┐ ┌ ARR ─────┐ ┌ Active subs┐ ┌ Churn ───┐ ┌ Health ●green ┐ │
│ │ $48,470  │ │ $581,640 │ │    27      │ │  2.1%    │ │ all systems   │ │
│ └──────────┘ └──────────┘ └────────────┘ └──────────┘ └───────────────┘ │
│ MRR by plan  ▇ Starter ▇▇ Pro ▇▇▇ Enterprise     [range ▾] [Export]     │
│ Trial→paid conversion · new vs churned (chart)                          │
└──────────────────────────────────────────────────────────────────────────┘
GET /admin/metrics
```

### C2. Customers `/admin/customers` → `/:id`
```
┌ Customers                                   [🔍] [Onboard brokerage]     ┐
│ Name             Plan   Statut  MRR    Docs    Prov  Lang  Créé          │
│ Cabinet Tremblay PRO    ●actif  $1999  62/500  QC    FR    2024-02 [View]│
│ Smith Brokers    STARTER ●actif $499   80/100  ON    EN    2025-11 [View]│
├──────────────────────────────────────────────────────────────────────────┤
│ Detail /:id : profil · abonnement · usage trend · volume docs · équipe   │
│   · audit · [Impersonate (consent, audité)] · [Changer forfait] · Stripe │
└──────────────────────────────────────────────────────────────────────────┘
GET /admin/brokerages · POST /admin/brokerage
```

### C3. Tickets `/admin/tickets`
```
┌ Support                                                  [filters ▾]     ┐
│ Sujet              Cabinet          Prio  Statut    Assigné   SLA        │
│ Extraction wrong   Cabinet Tremblay High  ●open     —         2h ⧗       │
│ Invoice FR missing Smith Brokers    Med   ⧗pending  Alex      —          │
│ row → thread · notes internes · lier document/customer · [Répondre][Fermer]│
└──────────────────────────────────────────────────────────────────────────┘
```

### C4. System Health `/admin/health`
```
┌ System Health                                          [Refresh]         ┐
│ API ●  DB ●  Gemini ●  Stripe ●  n8n ●  Storage ●   (green/yellow/red)   │
│ Recent failures: failed docs · retries · 5xx · webhook delivery          │
│ Queue depth · latency · 90-day purge cron: last run 03:00 ✓              │
│ [View failed documents] [Re-run purge] [Open logs]                       │
└──────────────────────────────────────────────────────────────────────────┘
GET /healthz · GET /admin/metrics(system_health)
```

---

## Responsive notes
- < 1024px: sidebar → top drawer (hamburger); topbar keeps usage pill + lang + bell.
- < 768px: tables (queue, team, invoices, customers) collapse to stacked cards;
  Review screen stacks PDF over fields (PDF in a collapsible top panel).
- Touch targets ≥ 44px; ⌘K available on desktop, search field on mobile.
