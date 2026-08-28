"""90-day document auto-delete (legal retention baseline).

Run daily via cron / systemd timer / pg_cron:
    python cron_cleanup.py

Deletes documents older than 90 days (and their stored files), keeping audit
logs intact (audit_logs are retained for compliance).
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

from sqlalchemy import text

from config import settings
from database import SessionLocal
from models import AuditLog, Document

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("brokerage.cron")

RETENTION_DAYS = 90


def purge_old_documents() -> int:
    db = SessionLocal()
    deleted = 0
    try:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=RETENTION_DAYS)
        old = db.query(Document).filter(Document.created_at < cutoff).all()
        for doc in old:
            _delete_file(doc.file_path)
            db.add(
                AuditLog(
                    brokerage_id=doc.brokerage_id,
                    document_id=None,  # doc is being removed
                    action=f"document_purged_retention id={doc.id}",
                    ip_address=None,
                )
            )
            db.delete(doc)
            deleted += 1
        db.commit()
        logger.info("Purged %d documents older than %d days", deleted, RETENTION_DAYS)
        return deleted
    finally:
        db.close()


def _delete_file(file_path: str | None) -> None:
    if not file_path:
        return
    # local demo storage
    if file_path.startswith("local_storage/"):
        p = Path(__file__).parent / file_path
        if p.exists():
            p.unlink()
        return
    # Supabase storage
    if settings.supabase_url and settings.supabase_service_key:
        try:
            from supabase import create_client

            client = create_client(settings.supabase_url, settings.supabase_service_key)
            client.storage.from_(settings.supabase_storage_bucket).remove([file_path])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to delete storage object %s: %s", file_path, exc)


if __name__ == "__main__":
    purge_old_documents()
