"""Build the bilingual draft email a broker reviews before any client contact.

Legal baseline baked in:
  - Every email states "Draft for review by licensed broker" (AMF: never sent
    directly to clients; broker approval required).
  - CASL: includes physical mailing address + unsubscribe link.
"""
from __future__ import annotations

from typing import Any

from config import settings
from i18n import t


def build_draft_email(language: str, extracted: dict[str, Any]) -> str:
    lang = "fr" if language == "fr" else "en"
    policy = extracted.get("policy_number") or ("N/A" if lang == "en" else "S.O.")

    lines: list[str] = []
    lines.append(t(lang, "email_subject", policy=policy))
    lines.append("")
    lines.append(t(lang, "email_greeting"))
    lines.append("")
    lines.append(t(lang, "email_intro"))
    lines.append("")

    # key fields
    field_map = [
        ("policy_number", "policy_number"),
        ("named_insured", "named_insured"),
        ("policy_type", "policy_type"),
        ("effective_date", "effective_date"),
        ("expiry_date", "expiry_date"),
    ]
    for data_key, label_key in field_map:
        val = extracted.get(data_key)
        if val:
            lines.append(f"- {t(lang, label_key)}: {val}")

    # coverage / deductibles
    cov = extracted.get("coverage_limits")
    if isinstance(cov, dict) and cov:
        lines.append("")
        head = "Coverage limits:" if lang == "en" else "Limites de couverture :"
        lines.append(head)
        for k, v in cov.items():
            lines.append(f"  • {k}: {v}")

    ded = extracted.get("deductibles")
    if isinstance(ded, dict) and ded:
        head = "Deductibles:" if lang == "en" else "Franchises :"
        lines.append(head)
        for k, v in ded.items():
            lines.append(f"  • {k}: {v}")

    # action items
    actions = extracted.get("action_items")
    if isinstance(actions, list) and actions:
        lines.append("")
        lines.append(t(lang, "email_action_items"))
        for item in actions:
            lines.append(f"  • {item}")

    # ---- legal footer ----
    lines.append("")
    lines.append("—" * 20)
    lines.append(f"⚠  {t(lang, 'email_disclaimer')}")
    lines.append("")
    lines.append(t(lang, "email_regards"))
    lines.append(settings.company_legal_name)
    lines.append(settings.company_mailing_address)  # CASL: physical address
    lines.append(t(lang, "email_unsubscribe", url=settings.company_unsubscribe_url))
    return "\n".join(lines)
