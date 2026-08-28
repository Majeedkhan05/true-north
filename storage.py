"""Supabase Storage helpers + PDF text extraction (pdfplumber + pytesseract OCR).

In DEMO_MODE (or without Supabase creds) files are written to ./local_storage so
the pipeline runs end-to-end offline.
"""
from __future__ import annotations

import io
import hashlib
import logging
from pathlib import Path

from config import settings

logger = logging.getLogger("brokerage.storage")

LOCAL_DIR = Path(__file__).parent / "local_storage"


def sha256_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
#  Upload
# ---------------------------------------------------------------------------
def upload_pdf(brokerage_id: str, file_hash: str, data: bytes) -> str:
    """Store the PDF and return a storage path/key."""
    object_path = f"{brokerage_id}/{file_hash}.pdf"

    if settings.demo_mode or not (settings.supabase_url and settings.supabase_service_key):
        LOCAL_DIR.mkdir(exist_ok=True)
        (LOCAL_DIR / f"{file_hash}.pdf").write_bytes(data)
        return f"local_storage/{file_hash}.pdf"

    from supabase import create_client

    client = create_client(settings.supabase_url, settings.supabase_service_key)
    client.storage.from_(settings.supabase_storage_bucket).upload(
        path=object_path,
        file=data,
        file_options={"content-type": "application/pdf", "upsert": "true"},
    )
    return object_path


# ---------------------------------------------------------------------------
#  Download (used by /retry/process to re-run extraction on a stored file)
# ---------------------------------------------------------------------------
def download_pdf(file_path: str | None) -> bytes | None:
    """Fetch a previously stored PDF, or None if unavailable."""
    if not file_path:
        return None
    if file_path.startswith("local_storage/"):
        p = Path(__file__).parent / file_path
        return p.read_bytes() if p.exists() else None
    if settings.supabase_url and settings.supabase_service_key:
        try:
            from supabase import create_client

            client = create_client(settings.supabase_url, settings.supabase_service_key)
            return client.storage.from_(settings.supabase_storage_bucket).download(file_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to download %s: %s", file_path, exc)
    return None


# ---------------------------------------------------------------------------
#  Text extraction:  pdfplumber first, OCR fallback
# ---------------------------------------------------------------------------
def extract_text(data: bytes) -> str:
    """Extract text from a PDF. Falls back to OCR for scanned/image PDFs."""
    text = _extract_with_pdfplumber(data)
    if len(text.strip()) >= 40:  # enough real text -> trust the digital layer
        return text

    logger.info("pdfplumber yielded little text; falling back to OCR")
    ocr = _extract_with_ocr(data)
    return ocr if len(ocr.strip()) > len(text.strip()) else text


def _extract_with_pdfplumber(data: bytes) -> str:
    try:
        import pdfplumber

        chunks: list[str] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                chunks.append(page.extract_text() or "")
        return "\n".join(chunks)
    except Exception as exc:  # noqa: BLE001 — degrade gracefully to OCR
        logger.warning("pdfplumber failed: %s", exc)
        return ""


def _extract_with_ocr(data: bytes) -> str:
    try:
        import pytesseract
        from pdf2image import convert_from_bytes

        images = convert_from_bytes(data)
        return "\n".join(pytesseract.image_to_string(img) for img in images)
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCR failed (is tesseract/poppler installed?): %s", exc)
        return ""
