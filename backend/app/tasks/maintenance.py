"""One-off / manual maintenance helpers (e.g. FTS rebuild).

Scheduled cron-style jobs live in :mod:`app.tasks.maintenance_tasks` and are
registered from :mod:`app.scheduler`.
"""

import asyncio
from app.database import SessionLocal
from sqlalchemy import text
from app.utils.logger import get_logger

logger = get_logger(__name__)

async def rebuild_fts_index():
    """Rebuild the SQLite FTS5 search index."""
    logger.info("Rebuilding FTS index...")
    db = SessionLocal()
    try:
        # 1. Clear existing index
        db.execute(text("DELETE FROM content_fts"))
        
        # 2. Re-populate from contents table
        # We use rowid to preserve the link between contents and content_fts
        db.execute(text("""
            INSERT INTO content_fts(rowid, id, title, summary, full_content)
            SELECT rowid, id, title, summary, full_content FROM contents
        """))
        
        db.commit()
        logger.info("FTS index rebuild complete.")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"FTS index rebuild failed: {e}")
        return False
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(rebuild_fts_index())
