"""Tasks for post-fetch content processing (non-blocking enrichment).

Runs after fetch so the fetch pipeline stays fast.
"""

import asyncio

from app.features import KEYWORD_MONITORING_ENABLED
from app.background import get_llm_semaphore, task_tracker
from app.utils.logger import get_logger, bind_job_id, restore_job_id
from app.utils.text import truncate_content

logger = get_logger(__name__)


async def process_new_content(content_id: str, job_id: str | None = None):
    """Process a freshly saved content item (cookie full-text + keywords)."""
    token = bind_job_id(job_id) if job_id else None
    try:
        sem = get_llm_semaphore()
        async with sem:
            await task_tracker.start_process()
            try:
                await _process_new_content_async(content_id)
            finally:
                await task_tracker.end_process()
    finally:
        if token is not None:
            restore_job_id(token)


async def _process_new_content_async(content_id: str):
    """Async implementation of content processing."""
    from sqlalchemy.orm import joinedload

    from app.database import SessionLocal
    from app.models import Content, Keyword
    from app.processors import ContentProcessor
    from app.processors.keyword_matcher import KeywordMatcher
    from app.services.content_quality_service import merge_content_quality_metadata
    from app.services.scoring_service import merge_baseline_scoring_metadata
    from app.tasks.fetch_auth_helpers import try_parse_auth_credentials
    from app.utils.cookies import normalize_cookie_dict

    db = SessionLocal()
    try:
        content = (
            db.query(Content)
            .options(joinedload(Content.source))
            .filter(Content.id == content_id)
            .first()
        )
        if not content:
            logger.error(f"Content not found: {content_id}")
            return

        source = content.source
        processor = ContentProcessor()

        # Cookie full-text enrichment
        if source and source.auth_config_id:
            try:
                creds = try_parse_auth_credentials(source.auth_config)
                cookies = normalize_cookie_dict(creds.get("cookies"))
                if cookies and (not content.full_content or len(content.full_content) < 600):
                    fetched = await processor._fetch_full_text_with_cookies(
                        content.original_url, cookies
                    )
                    if fetched and len(fetched) > len(content.full_content or ""):
                        content.full_content = truncate_content(fetched, url=content.original_url or "")
            except Exception as exc:
                logger.debug(f"Cookie enrichment skipped for {content_id}: {exc}")

        # Keyword matching
        if KEYWORD_MONITORING_ENABLED:
            keywords = db.query(Keyword).filter(Keyword.enabled == True).all()
            if keywords:
                matcher = KeywordMatcher()
                content.keyword_matches = matcher.match(
                    content.title or "",
                    content.full_content or content.summary or "",
                    keywords,
                )

        # Clear pending flag
        meta = dict(content.metadata_ or {})
        meta.pop("ai_pending", None)
        meta = merge_content_quality_metadata(
            meta,
            title=content.title or "",
            full_content=content.full_content,
            summary=content.summary,
            translated_summary=content.translated_summary,
        )
        meta = merge_baseline_scoring_metadata(
            meta,
            title=content.title or "",
            summary=content.translated_summary or content.summary,
            full_content=content.full_content,
            source_metadata=source.metadata_ if source else {},
        )
        content.metadata_ = meta

        db.commit()
        logger.info(f"Post-processed content: {content.title[:50]}")

        # Keyword alert notifications
        if KEYWORD_MONITORING_ENABLED and content.keyword_matches:
            _dispatch_keyword_alerts(db, content)

    except Exception as exc:
        logger.error(f"process_new_content failed for {content_id}: {exc}")
    finally:
        db.close()


def _dispatch_keyword_alerts(db, content):
    """Schedule keyword alert emails (fire-and-forget)."""
    from app.models import Keyword
    from app.tasks.email_tasks import send_keyword_alert

    async def _deliver_keyword_alert(keyword: str) -> None:
        try:
            await send_keyword_alert(str(content.id), keyword, content.title)
        except Exception as exc:
            logger.warning("Keyword alert dispatch failed for %s: %s", content.id, exc)

    for match in content.keyword_matches:
        keyword_obj = db.query(Keyword).filter(Keyword.id == match["id"]).first()
        if keyword_obj and keyword_obj.notify:
            try:
                asyncio.create_task(_deliver_keyword_alert(match["keyword"]))
            except RuntimeError:
                # No running loop (shouldn't happen normally)
                pass


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
        await task_queue.enqueue_process(content_id, job_id=None)


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
        keywords = db.query(Keyword).filter(Keyword.enabled == True).all()
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
