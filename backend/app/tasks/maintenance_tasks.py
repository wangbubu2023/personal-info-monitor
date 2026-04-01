"""Maintenance tasks for data cleanup and housekeeping."""

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
