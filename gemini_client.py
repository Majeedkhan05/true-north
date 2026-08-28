"""Gemini 2.5 Flash wrapper for insurance document extraction.

Loads prompt.txt, injects the brokerage language, strips PII, calls Gemini and
returns a parsed JSON dict. In DEMO_MODE (or when no API key is set) it returns a
deterministic stub so the full pipeline runs offline.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from config import settings
from pii_utils import strip_for_ai

PROMPT_PATH = Path(__file__).parent / "prompt.txt"


def _load_prompt(language: str) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    return template.replace("{{LANGUAGE}}", language)


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model response."""
    text = text.strip()
    # strip ```json fences if present
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in model response")
    return json.loads(text[start : end + 1])


def _demo_extraction(document_text: str, language: str) -> dict[str, Any]:
    """Deterministic offline stub mirroring the real schema."""
    fr = language == "fr"
    pol = None
    m = re.search(r"\b([A-Z]{2,4}[-\s]?\d{4,10})\b", document_text)
    if m:
        pol = m.group(1)
    return {
        "policy_number": pol or "INT-2024-558831",
        "named_insured": "ACME Logistics Inc." if not fr else "Les Transports ACME inc.",
        "policy_type": "Commercial Property" if not fr else "Biens commerciaux",
        "coverage_limits": {"Building": "2,000,000 CAD", "Liability": "5,000,000 CAD"},
        "deductibles": {"All perils": "5,000 CAD"},
        "effective_date": "2024-07-01",
        "expiry_date": "2025-07-01",
        "endorsements": ["Equipment Breakdown", "Flood Sublimit"],
        "action_items": (
            ["Confirmer le renouvellement 30 jours avant l'échéance."]
            if fr
            else ["Confirm renewal 30 days before expiry."]
        ),
        "confidence": 88,
    }


def extract_document(document_text: str, language: str) -> dict[str, Any]:
    """Run extraction. `language` is 'en' or 'fr'."""
    safe_text = strip_for_ai(document_text)

    if settings.demo_mode or not settings.gemini_api_key:
        return _demo_extraction(safe_text, language)

    import google.generativeai as genai

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(
        settings.gemini_model,
        system_instruction=_load_prompt(language),
        generation_config={"response_mime_type": "application/json", "temperature": 0.1},
    )
    resp = model.generate_content(
        f"LANGUAGE={language}\n\nDOCUMENT TEXT:\n{safe_text}"
    )
    return _extract_json(resp.text)
