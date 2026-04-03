"""Tasks for post-fetch content processing (non-blocking enrichment).

Runs after fetch so the fetch pipeline stays fast.
"""

import asyncio

from app.features import KEYWORD_MONITORING_ENABLED
from app.background import get_llm_semaphore, task_tracker
from app.utils.logger import get_logger
from app.utils.text import truncate_content

logger = get_logger(__name__)


async def process_new_content(content_id: str):
    """Process a freshly saved content item (cookie full-text + keywords)."""
    sem = get_llm_semaphore()
    async with sem:
        await task_tracker.start_process()
        try:
            await _process_new_content_async(content_id)
        finally:
            await task_tracker.end_process()


async def _process_new_content_async(content_id: str):
    """Async implementation of content processing."""
    from sqlalchemy.orm import joinedload

    from app.database import SessionLocal
    from app.models import Content, Keyword
    from app.processors import ContentProcessor
    from app.processors.keyword_matcher import KeywordMatcher
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
                search_text = f"{content.title} {content.full_content or content.summary or ''}"
                content.keyword_matches = matcher.match(search_text, keywords)

        # Clear pending flag
        meta = dict(content.metadata_ or {})
        meta.pop("ai_pending", None)
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

    for match in content.keyword_matches:
        keyword_obj = db.query(Keyword).filter(Keyword.id == match["id"]).first()
        if keyword_obj and keyword_obj.notify:
            # Import here to avoid circular
            import asyncio
            from app.tasks.email_tasks import send_keyword_alert
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(
                    asyncio.ensure_future,
                    send_keyword_alert(str(content.id), match["keyword"], content.title)
                )
            except RuntimeError:
                # No running loop (shouldn't happen normally)
                pass


async def process_content(content_id: str, regenerate_summary: bool = False, retranslate: bool = False):
    """Reprocess an existing content item (manual trigger from UI)."""
    sem = get_llm_semaphore()
    async with sem:
        await _process_content_async(content_id, regenerate_summary, retranslate)


async def _process_content_async(content_id: str, regenerate_summary: bool, retranslate: bool):
    from app.database import SessionLocal
    from app.models import Content
    from app.processors import ContentProcessor

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
        await task_queue.enqueue_process(content_id)


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
        offset = 0

        while True:
            contents = db.query(Content).offset(offset).limit(batch_size).all()
            if not contents:
                break

            for content in contents:
                search_text = f"{content.title} {content.full_content or content.summary or ''}"
                matches = matcher.match(search_text, keywords)
                if matches != content.keyword_matches:
                    content.keyword_matches = matches
                    updated_count += 1

            db.commit()
            offset += batch_size

        logger.info(f"Updated keyword matches for {updated_count} contents")
    finally:
        db.close()
