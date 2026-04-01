"""Tasks for fetching content from sources — high-concurrency async engine."""

import asyncio
from datetime import timedelta

from app.background import (
    domain_limiter,
    fetch_lock,
    get_fetch_semaphore,
    task_tracker,
)
from app.config import get_settings
from app.features import PODCAST_SOURCES_ENABLED
from app.models.source import SourceType
from app.pipeline.coordinator import run_fetch_pipeline
from app.tasks.fetch_orchestrator import persist_fetch_task_exception
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger
from app.utils.url import normalize_host

logger = get_logger(__name__)
settings = get_settings()


async def fetch_source(source_id: str, manual_trigger: bool = False):
    """Fetch content from a single source. Runs pipeline in a thread."""
    logger.info(f"Starting fetch for source: {source_id} (manual={manual_trigger})")

    sem = get_fetch_semaphore()
    async with sem:
        await task_tracker.start_fetch()
        try:
            await _do_fetch(source_id, manual_trigger)
        finally:
            await task_tracker.end_fetch()


async def _do_fetch(source_id: str, manual_trigger: bool):
    from app.database import SessionLocal
    from app.models import Source

    lock_ttl = 300
    lock_acquired = False

    try:
        # Acquire per-source lock
        def _query_and_fetch():
            nonlocal lock_acquired, lock_ttl
            db = SessionLocal()
            try:
                source = db.query(Source).filter(Source.id == source_id).first()
                if not source:
                    logger.error(f"Source not found: {source_id}")
                    return {"status": "error", "message": "Source not found"}

                lock_ttl = max(300, int((source.fetch_interval or 60) * 60))
                lock_acquired = fetch_lock.acquire(source_id, lock_ttl)
                if not lock_acquired:
                    logger.info(f"Skip duplicate fetch for source: {source_id}")
                    return {"status": "skipped", "message": "Already fetching"}

                if not source.enabled and not manual_trigger:
                    return {"status": "skipped", "message": "Source is disabled"}
                if not PODCAST_SOURCES_ENABLED:
                    source_type = source.type.value if hasattr(source.type, "value") else str(source.type)
                    if source_type == "podcast":
                        return {"status": "skipped", "message": "Podcast sources are disabled"}

                # Domain rate limit
                domain = normalize_host(source.url)
                if not domain_limiter.acquire(domain):
                    logger.info(f"Rate-limited domain for source: {source_id} ({domain})")
                    fetch_lock.release(source_id)
                    lock_acquired = False
                    return {"status": "skipped", "message": "Domain rate limited"}

                result = asyncio.run(run_fetch_pipeline(db, source, manual_trigger))

                # Collect new content IDs for AI processing
                new_ids = []
                if result.get("saved", 0) > 0:
                    new_ids = result.get("new_content_ids", [])

                return {**result, "new_content_ids": new_ids}
            finally:
                if lock_acquired:
                    fetch_lock.release(source_id)
                db.close()

        result = await asyncio.to_thread(_query_and_fetch)

        # Dispatch non-blocking post-processing for new content.
        new_ids = result.get("new_content_ids", [])
        if new_ids:
            from app.tasks.process_tasks import process_new_content
            for cid in new_ids:
                asyncio.create_task(process_new_content(str(cid)))

        return result

    except Exception as exc:
        logger.error(f"Fetch failed for {source_id}: {exc}")
        await asyncio.to_thread(persist_fetch_task_exception, source_id, exc)


async def fetch_all_sources(manual_trigger: bool = False):
    """Fetch all enabled sources in parallel."""
    logger.info("Fetching all enabled sources")

    from app.database import SessionLocal
    from app.models import Source

    def _query_sources():
        db = SessionLocal()
        try:
            query = db.query(Source).filter(Source.enabled == True)
            if not PODCAST_SOURCES_ENABLED:
                query = query.filter(Source.type != SourceType.PODCAST)
            sources = query.all()
            return [str(s.id) for s in sources]
        finally:
            db.close()

    source_ids = await asyncio.to_thread(_query_sources)

    scheduled = 0
    for sid in source_ids:
        if fetch_lock.is_locked(sid):
            continue
        asyncio.create_task(fetch_source(sid, manual_trigger=manual_trigger))
        scheduled += 1

    logger.info(f"Dispatched {scheduled}/{len(source_ids)} fetch tasks")
    return {"status": "success", "total": len(source_ids), "scheduled": scheduled}


async def check_and_fetch_due_sources():
    """Scheduled job: check for sources due for fetching and dispatch."""
    logger.info("Checking for sources due for fetching")

    from app.database import SessionLocal
    from app.models import Source

    def _query_due():
        db = SessionLocal()
        try:
            now = utcnow_naive()
            query = db.query(Source).filter(Source.enabled == True)
            if not PODCAST_SOURCES_ENABLED:
                query = query.filter(Source.type != SourceType.PODCAST)
            sources = query.all()

            due = []
            for source in sources:
                if not source.last_fetched_at:
                    due.append(str(source.id))
                else:
                    multiplier = 2 ** min(source.error_count or 0, 5)
                    interval = (source.fetch_interval or 60) * multiplier
                    next_fetch = source.last_fetched_at + timedelta(minutes=interval)
                    if now >= next_fetch:
                        due.append(str(source.id))
            return due
        finally:
            db.close()

    due_ids = await asyncio.to_thread(_query_due)

    scheduled = 0
    for sid in due_ids:
        if fetch_lock.is_locked(sid):
            continue
        asyncio.create_task(fetch_source(sid))
        scheduled += 1

    logger.info(f"Scheduled {scheduled}/{len(due_ids)} due sources")
