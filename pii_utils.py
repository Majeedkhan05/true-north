"""PII handling.

  - mask_for_logs(text)   -> redacts PII so logs never store raw PII
  - strip_for_ai(text)    -> removes SIN / phone / address before sending to Gemini
  - validate_for_db(data) -> sanity-checks a record before persistence

Canadian-specific patterns: SIN (9 digits, often grouped 3-3-3), phone numbers,
postal codes, email addresses, and street addresses.
"""
from __future__ import annotations

import re
from typing import Any

# --- patterns --------------------------------------------------------------
SIN_RE = re.compile(r"\b\d{3}[-\s]?\d{3}[-\s]?\d{3}\b")
PHONE_RE = re.compile(
    r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b"
)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
POSTAL_RE = re.compile(r"\b[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z][ -]?\d[ABCEGHJ-NPRSTV-Z]\d\b", re.I)
# Street address: number + street words (covers EN + common FR: rue, av., boul., chemin)
ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+(?:[A-Za-zÀ-ÿ.'\-]+\s+){0,4}"
    r"(?:street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|court|ct|"
    r"rue|av|avenue|boul|boulevard|chemin|ch|montée|rang|place|pl)\b\.?",
    re.I,
)


def mask_for_logs(text: str | None) -> str:
    """Redact PII for safe logging. Never returns raw SIN/phone/email/address."""
    if not text:
        return ""
    out = SIN_RE.sub("[SIN]", text)
    out = PHONE_RE.sub("[PHONE]", out)
    out = EMAIL_RE.sub("[EMAIL]", out)
    out = ADDRESS_RE.sub("[ADDRESS]", out)
    out = POSTAL_RE.sub("[POSTAL]", out)
    return out


def strip_for_ai(text: str | None) -> str:
    """Remove high-sensitivity PII before sending text to Gemini.

    SIN, phone numbers and street addresses are never required to extract policy
    structure, so we strip them outright. Names/policy numbers are preserved
    because they ARE the extraction target.
    """
    if not text:
        return ""
    out = SIN_RE.sub("[REDACTED-SIN]", text)
    out = PHONE_RE.sub("[REDACTED-PHONE]", out)
    out = ADDRESS_RE.sub("[REDACTED-ADDRESS]", out)
    return out


def validate_for_db(data: dict[str, Any]) -> dict[str, Any]:
    """Final guard before persisting an extraction record.

    - Ensures no raw SIN leaked into stored fields (defense in depth).
    - Coerces confidence into 0-100.
    """
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, str):
            cleaned[key] = SIN_RE.sub("[SIN]", value)
        else:
            cleaned[key] = value

    conf = cleaned.get("confidence")
    if conf is not None:
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            conf = 0.0
        cleaned["confidence"] = max(0.0, min(100.0, conf))
    return cleaned


def contains_pii(text: str | None) -> bool:
    if not text:
        return False
    return bool(
        SIN_RE.search(text) or PHONE_RE.search(text) or ADDRESS_RE.search(text)
    )
