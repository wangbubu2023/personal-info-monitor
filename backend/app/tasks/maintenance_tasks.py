"""Scheduled maintenance jobs (cleanup, lock purge, markdown export).

Ad-hoc helpers such as FTS rebuild live in :mod:`app.tasks.maintenance`.
"""

import asyncio
from datetime import timedelta

from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def cleanup_old_content(retention_days: int = 90):
    """Clean up old content beyond the retention period."""
    def _cleanup():
        from app.database import SessionLocal
        from app.models import Content

        cutoff_date = utcnow_naive() - timedelta(days=retention_days)

        db = SessionLocal()
        try:
            deleted_count = (
                db.query(Content)
                .filter(
                    Content.created_at < cutoff_date,
                    Content.favorited == False,
                    Content.archived == False,
                )
                .delete(synchronize_session=False)
            )
            db.commit()
            logger.info(f"Cleaned up {deleted_count} old content items")
        except Exception as e:
            db.rollback()
            logger.error(f"Error during cleanup: {e}")
        finally:
            db.close()

    await asyncio.to_thread(_cleanup)


async def cleanup_error_logs():
    """Reset error counts for sources that have recovered."""
    def _cleanup():
        from app.database import SessionLocal
        from app.models import Source

        cutoff = utcnow_naive() - timedelta(hours=24)

        db = SessionLocal()
        try:
            updated_count = (
                db.query(Source)
                .filter(
                    Source.error_count > 0,
                    Source.last_fetched_at > cutoff,
                    Source.last_error == None,
                )
                .update({"error_count": 0}, synchronize_session=False)
            )
            db.commit()
            logger.info(f"Reset error counts for {updated_count} sources")
        except Exception as e:
            db.rollback()
            logger.error(f"Error during error log cleanup: {e}")
        finally:
            db.close()

    await asyncio.to_thread(_cleanup)


async def run_markdown_export(since_hours: int = 2):
    """Run incremental markdown export task."""
    from datetime import timedelta
    from app.database import AsyncSessionLocal
    from app.services.system_settings import get_system_settings_async
    from app.exporters.markdown_exporter import MarkdownExporter

    async with AsyncSessionLocal() as db:
        try:
            settings = await get_system_settings_async(db)
            if not settings.get("markdown_export_enabled"):
                return

            export_dir = settings.get("markdown_export_dir")
            if not export_dir:
                export_dir = "~/.pim/knowledge-base"
                
            exporter = MarkdownExporter(export_dir)
            since = utcnow_naive() - timedelta(hours=since_hours)
            
            count = await exporter.export_incremental(db, since)
            if count > 0:
                logger.info(f"Exported {count} contents to Markdown at {export_dir}")
        except Exception as e:
            logger.error(f"Error running markdown export: {e}")


async def purge_expired_runtime_locks():
    """Remove stale fetch coordination rows from runtime_locks."""

    def _purge():
        from app.services.runtime_lock_service import runtime_lock_service

        n = runtime_lock_service.purge_expired()
        if n:
            logger.info("Purged %d expired runtime lock row(s)", n)

    await asyncio.to_thread(_purge)
