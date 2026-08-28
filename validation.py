"""Validation of Gemini output: policy-number regex, date validation, numeric checks.

Returns a (cleaned_data, issues, confidence_penalty) so the API can both store a
sanitized record and surface problems as broker action items.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

# Canadian insurance policy numbers vary by carrier; accept common shapes:
# letters/digits/dashes, 5-20 chars, at least one digit.
POLICY_NUMBER_RE = re.compile(r"^(?=.*\d)[A-Z0-9][A-Z0-9\-\/ ]{3,19}$", re.I)

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y")


def validate_policy_number(value: Any) -> tuple[Any, str | None]:
    if value in (None, "", "null"):
        return None, "Missing policy number."
    text = str(value).strip()
    if not POLICY_NUMBER_RE.match(text):
        return text, f"Policy number '{text}' has an unusual format — verify manually."
    return text, None


def normalize_date(value: Any) -> tuple[str | None, str | None]:
    """Return (ISO date str, issue). None value is allowed (not an error)."""
    if value in (None, "", "null"):
        return None, None
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            d = dt.datetime.strptime(text, fmt).date()
            return d.isoformat(), None
        except ValueError:
            continue
    return None, f"Could not parse date '{text}' — request a corrected document."


def validate_numeric_fields(coverage_limits: Any, deductibles: Any) -> list[str]:
    """Numeric sanity: amounts must contain digits; deductible < any limit ideally."""
    issues: list[str] = []

    def _amounts(obj: Any) -> list[float]:
        vals: list[float] = []
        if isinstance(obj, dict):
            for v in obj.values():
                num = _to_number(v)
                if num is not None:
                    vals.append(num)
        return vals

    if isinstance(coverage_limits, dict):
        for k, v in coverage_limits.items():
            if _to_number(v) is None:
                issues.append(f"Coverage limit for '{k}' is not numeric — verify.")
    if isinstance(deductibles, dict):
        for k, v in deductibles.items():
            if _to_number(v) is None:
                issues.append(f"Deductible for '{k}' is not numeric — verify.")

    limits = _amounts(coverage_limits)
    deds = _amounts(deductibles)
    if limits and deds and max(deds) > max(limits):
        issues.append("A deductible exceeds the largest coverage limit — confirm.")
    return issues


def _to_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    digits = re.sub(r"[^\d.]", "", str(value))
    if not digits or digits == ".":
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def validate_extraction(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Validate & normalize a Gemini extraction. Returns (data, issues)."""
    issues: list[str] = []
    data = dict(data)

    pol, issue = validate_policy_number(data.get("policy_number"))
    data["policy_number"] = pol
    if issue:
        issues.append(issue)

    for date_field in ("effective_date", "expiry_date"):
        iso, issue = normalize_date(data.get(date_field))
        data[date_field] = iso
        if issue:
            issues.append(issue)

    # effective must precede expiry
    eff, exp = data.get("effective_date"), data.get("expiry_date")
    if eff and exp and eff > exp:
        issues.append("Effective date is after expiry date — verify document.")

    issues.extend(
        validate_numeric_fields(data.get("coverage_limits"), data.get("deductibles"))
    )

    # Confidence into [0,100]
    try:
        conf = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        conf = 0.0
    data["confidence"] = max(0.0, min(100.0, conf))

    # Merge validation issues into action_items so the broker sees them.
    existing = data.get("action_items") or []
    if not isinstance(existing, list):
        existing = [str(existing)]
    data["action_items"] = existing + issues

    return data, issues
