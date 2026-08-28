"""Bilingual (EN / FR) strings and language-derivation helpers.

Used by the FastAPI layer (draft emails), the Streamlit UI, and invoices so the
whole product speaks one language per brokerage.

French strings are written in natural Canadian (Quebec) French.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
#  Postal-code -> default language
#
#  Canada Post reality:  G, H, J  = Québec  ->  French
#                        K, L, M, N, P = Ontario -> English
#
#  The product spec's intent is "Quebec -> French, Ontario -> English". The
#  parenthetical letter list in the brief conflated the two provinces (it can't
#  map K-P to BOTH French and English), so we implement the geographically
#  correct mapping below. Quebec FSAs always start with G, H or J.
# ---------------------------------------------------------------------------
QUEBEC_FSA_LETTERS = {"G", "H", "J"}
ONTARIO_FSA_LETTERS = {"K", "L", "M", "N", "P"}


def language_for_postal_code(postal_code: str | None) -> str:
    """Return 'fr' for Quebec postal codes, else 'en'. Defaults to 'en'."""
    if not postal_code:
        return "en"
    first = postal_code.strip().upper()[:1]
    if first in QUEBEC_FSA_LETTERS:
        return "fr"
    return "en"


def normalize_language(value: str | None) -> str:
    return "fr" if (value or "").lower().startswith("fr") else "en"


# ---------------------------------------------------------------------------
#  UI / email string tables
# ---------------------------------------------------------------------------
T = {
    "en": {
        # language selector
        "choose_language": "Choose your language",
        "english": "🇨🇦 English",
        "french": "🇨🇦 Français",
        "continue": "Continue",
        # nav / portal
        "client_portal": "Client Portal",
        "admin_panel": "Admin Panel",
        "documents": "Documents",
        "document_viewer": "Document Viewer",
        "extracted_data": "Extracted Data",
        "draft_email": "Draft Email",
        "approve": "Approve",
        "approved": "Approved",
        "billing": "Billing",
        "confidence": "Confidence",
        "status": "Status",
        "no_documents": "No documents yet. Forward a policy PDF to your intake mailbox.",
        "subscribe": "Subscribe / Manage Plan",
        "subscription_inactive": "Subscription inactive — processing is blocked.",
        "subscription_active": "Subscription active",
        "select_brokerage": "Select brokerage",
        "policy_number": "Policy number",
        "named_insured": "Named insured",
        "policy_type": "Policy type",
        "effective_date": "Effective date",
        "expiry_date": "Expiry date",
        # admin
        "onboard_brokerage": "Onboard Brokerage",
        "mrr": "Monthly Recurring Revenue",
        "active_subscriptions": "Active subscriptions",
        "system_health": "System health",
        "create": "Create",
        "plan": "Plan",
        "name": "Name",
        "email": "Email",
        "postal_code": "Postal code",
        # email
        "email_subject": "Draft for review — Insurance document {policy}",
        "email_greeting": "Hello,",
        "email_intro": "An incoming insurance document has been processed and the key "
        "details extracted below are ready for your review.",
        "email_disclaimer": "Draft for review by licensed broker. This message was "
        "not sent to the client.",
        "email_action_items": "Suggested action items:",
        "email_regards": "Regards,",
        "email_unsubscribe": "To stop these notifications, unsubscribe here: {url}",
    },
    "fr": {
        "choose_language": "Choisissez votre langue",
        "english": "🇨🇦 English",
        "french": "🇨🇦 Français",
        "continue": "Continuer",
        "client_portal": "Portail client",
        "admin_panel": "Panneau d'administration",
        "documents": "Documents",
        "document_viewer": "Visionneuse de documents",
        "extracted_data": "Données extraites",
        "draft_email": "Courriel provisoire",
        "approve": "Approuver",
        "approved": "Approuvé",
        "billing": "Facturation",
        "confidence": "Indice de confiance",
        "status": "Statut",
        "no_documents": "Aucun document pour l'instant. Transférez un PDF de police à "
        "votre boîte de réception.",
        "subscribe": "S'abonner / Gérer le forfait",
        "subscription_inactive": "Abonnement inactif — le traitement est bloqué.",
        "subscription_active": "Abonnement actif",
        "select_brokerage": "Choisir le cabinet de courtage",
        "policy_number": "Numéro de police",
        "named_insured": "Assuré désigné",
        "policy_type": "Type de police",
        "effective_date": "Date d'entrée en vigueur",
        "expiry_date": "Date d'échéance",
        "onboard_brokerage": "Intégrer un cabinet",
        "mrr": "Revenu récurrent mensuel",
        "active_subscriptions": "Abonnements actifs",
        "system_health": "État du système",
        "create": "Créer",
        "plan": "Forfait",
        "name": "Nom",
        "email": "Courriel",
        "postal_code": "Code postal",
        "email_subject": "Document à réviser — Document d'assurance {policy}",
        "email_greeting": "Bonjour,",
        "email_intro": "Un document d'assurance entrant a été traité. Les renseignements "
        "clés extraits ci-dessous sont prêts pour votre révision.",
        "email_disclaimer": "Document provisoire à réviser par un courtier autorisé. "
        "Ce message n'a pas été envoyé au client.",
        "email_action_items": "Mesures suggérées :",
        "email_regards": "Cordialement,",
        "email_unsubscribe": "Pour cesser de recevoir ces avis, désabonnez-vous ici : {url}",
    },
}


def t(lang: str, key: str, **kwargs) -> str:
    lang = normalize_language(lang)
    value = T.get(lang, T["en"]).get(key, T["en"].get(key, key))
    return value.format(**kwargs) if kwargs else value
