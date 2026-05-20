"""Post-fetch ingest finalization — non-LLM enrichment for freshly saved Content.

Runs after fetch so the fetch pipeline stays fast. This is the work
that closes out a Content row's *ingest* lifecycle (cookie-protected
full-text top-up + keyword matching + quality-metadata stamp +
baseline scoring + keyword-alert dispatch). It is intentionally
LLM-free: any AI summarization / translation belongs to the enrich
domain (handled later through a separate ``ai_pending`` queue).

Moved out of the legacy ``app.tasks.process_tasks.process_new_content``
function as part of Phase 3 step 5 of the module-refactor blueprint and
renamed ``finish_content`` to match the blueprint's ingest vocabulary.
Phase 7 retired the legacy ``process_new_content`` /
``_process_new_content_async`` re-exports; callers must import
:func:`finish_content` from this module.

Companion :func:`_dispatch_keyword_alerts` schedules keyword-alert
emails fire-and-forget; resolve it from this module directly (the
legacy ``app.tasks.process_tasks._dispatch_keyword_alerts`` re-export
was removed in Phase 7).
"""

from __future__ import annotations

import asyncio

from app.background import get_llm_semaphore, task_tracker
from app.features import KEYWORD_MONITORING_ENABLED
from app.utils.logger import bind_job_id, get_logger, restore_job_id
from app.utils.text import truncate_content

logger = get_logger(__name__)


async def finish_content(content_id: str, job_id: str | None = None) -> None:
    """Finalize a freshly saved Content row (cookie full-text + keyword + scoring)."""
    token = bind_job_id(job_id) if job_id else None
    try:
        sem = get_llm_semaphore()
        async with sem:
            await task_tracker.start_process()
            try:
                await _finish_content_async(content_id)
            finally:
                await task_tracker.end_process()
    finally:
        if token is not None:
            restore_job_id(token)


async def _finish_content_async(content_id: str) -> None:
    """Async implementation of ingest-finish enrichment."""
    from sqlalchemy.orm import joinedload

    from app.database import SessionLocal
    from app.domains.fetch.auth import try_parse_auth_credentials
    from app.models import Content, Keyword
    from app.processors.content_processor import ContentProcessor
    from app.processors.keyword_matcher import KeywordMatcher
    from app.services.content_quality_service import merge_content_quality_metadata
    from app.services.scoring_service import merge_baseline_scoring_metadata
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

        if KEYWORD_MONITORING_ENABLED:
            keywords = db.query(Keyword).filter(Keyword.enabled == True).all()  # noqa: E712 — SQLAlchemy boolean
            if keywords:
                matcher = KeywordMatcher()
                content.keyword_matches = matcher.match(
                    content.title or "",
                    content.full_content or content.summary or "",
                    keywords,
                )

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

        if KEYWORD_MONITORING_ENABLED and content.keyword_matches:
            _dispatch_keyword_alerts(db, content)

        # Phase 6: optional structural atomisation. ``atomize_content`` is
        # idempotent and never raises; when ``ATOMS_ENABLED=false`` it returns
        # False immediately, so the default flow stays bit-for-bit unchanged.
        try:
            from app.domains.atoms import atomize_content
            atomize_content(str(content.id))
        except Exception as exc:  # noqa: BLE001 - atoms is sidecar; never block ingest
            logger.debug("atomize_content sidecar failed for %s: %s", content_id, exc)

    except Exception as exc:
        logger.error(f"finish_content failed for {content_id}: {exc}")
    finally:
        db.close()


def _dispatch_keyword_alerts(db, content) -> None:
    """Schedule keyword-alert emails fire-and-forget."""
    from app.models import Keyword
    from app.domains.enrich.notifications.keyword_alert import send_keyword_alert

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


__all__ = [
    "finish_content",
    "_finish_content_async",
    "_dispatch_keyword_alerts",
    "logger",
]
