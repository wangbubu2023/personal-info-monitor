"""Backwards-compatible facade for post-fetch content processing tasks.

The non-LLM ingest-finalization path (formerly ``process_new_content`` +
``_process_new_content_async`` + ``_dispatch_keyword_alerts``) moved to
:mod:`app.domains.ingest.finish` in Phase 3 step 5 of the
module-refactor blueprint. Those callables are re-exported here under
their legacy names so existing callers — ``task_queue._process_worker``
(now using ``finish_content`` directly), ``app.tasks.__init__``, and
the keyword-alert / process-task tests — keep resolving without churn.

LLM-bearing manual reprocess paths (``process_content`` /
``_process_content_async``) and the keyword-refresh batch
(``update_keyword_matches`` / ``_update_keyword_matches_sync``) stay
here for now; they will move to ``tasks/enrich_jobs.py`` in Phase 4
once enrich is collapsed.
"""

from __future__ import annotations

import asyncio

from app.background import get_llm_semaphore, task_tracker  # noqa: F401 — patch target for tests
from app.domains.ingest.finish import (  # noqa: F401 — re-exported under legacy names
    _dispatch_keyword_alerts,
    _finish_content_async as _process_new_content_async,
    finish_content as process_new_content,
)
from app.features import KEYWORD_MONITORING_ENABLED  # noqa: F401 — patch target for tests
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def process_content(content_id: str, regenerate_summary: bool = False, retranslate: bool = False):
    """Reprocess an existing content item (manual trigger from UI)."""
    sem = get_llm_semaphore()
    async with sem:
        await _process_content_async(content_id, regenerate_summary, retranslate)


async def _process_content_async(content_id: str, regenerate_summary: bool, retranslate: bool):
    from app.config import get_settings
    from app.database import SessionLocal
    from app.models import Content
    from app.processors import ContentProcessor

    if (regenerate_summary or retranslate) and not get_settings().ai_processing_enabled:
        logger.info("AI processing disabled; skip manual reprocess for %s", content_id)
        return

    db = SessionLocal()
    try:
        content = db.query(Content).filter(Content.id == content_id).first()
        if not content:
            logger.error(f"Content not found: {content_id}")
            return

        processor = ContentProcessor()
        content = await processor.reprocess_content(
            content, regenerate_summary=regenerate_summary, retranslate=retranslate
        )
        db.commit()
        logger.info(f"Processed content: {content.title[:50]}")
    finally:
        db.close()


async def batch_process_contents(content_ids: list, regenerate_summary: bool = False, retranslate: bool = False):
    """Batch process multiple content items."""
    from app.tasks.task_queue import task_queue
    logger.info(f"Batch processing {len(content_ids)} contents")
    for content_id in content_ids:
        await task_queue.enqueue_ingest_finish(content_id, job_id=None)


async def update_keyword_matches():
    """Update keyword matches for all content."""
    await asyncio.to_thread(_update_keyword_matches_sync)


def _update_keyword_matches_sync():
    if not KEYWORD_MONITORING_ENABLED:
        logger.info("Keyword monitoring disabled; skip updating keyword matches")
        return

    from app.database import SessionLocal
    from app.models import Content, Keyword
    from app.processors.keyword_matcher import KeywordMatcher

    db = SessionLocal()
    try:
        keywords = db.query(Keyword).filter(Keyword.enabled == True).all()  # noqa: E712 — SQLAlchemy boolean
        if not keywords:
            logger.info("No active keywords to match")
            return

        matcher = KeywordMatcher()
        updated_count = 0
        batch_size = 100
        last_seen_id: str | None = None

        while True:
            query = db.query(Content).order_by(Content.id)
            if last_seen_id is not None:
                query = query.filter(Content.id > last_seen_id)
            query = query.limit(batch_size)
            contents = query.all()
            if not contents:
                break

            for content in contents:
                matches = matcher.match(
                    content.title or "",
                    content.full_content or content.summary or "",
                    keywords,
                )
                if matches != content.keyword_matches:
                    content.keyword_matches = matches
                    updated_count += 1

            db.commit()
            last_seen_id = contents[-1].id

        logger.info(f"Updated keyword matches for {updated_count} contents")
    finally:
        db.close()


__all__ = [
    "process_new_content",
    "_process_new_content_async",
    "_dispatch_keyword_alerts",
    "process_content",
    "batch_process_contents",
    "update_keyword_matches",
    "_update_keyword_matches_sync",
    "get_llm_semaphore",
    "task_tracker",
    "KEYWORD_MONITORING_ENABLED",
    "logger",
]
