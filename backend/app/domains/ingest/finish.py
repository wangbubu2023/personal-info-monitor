"""Post-fetch pipeline orchestration — fetch hydrate → ingest → summarize → score.

``finish_content`` is the single enqueue target after storage. It runs seven
pipeline stages (see MODULE_BOUNDARIES.md); only stages 4–5 may invoke LLM.
"""

from __future__ import annotations

import asyncio

from app.background import get_llm_semaphore, task_tracker
from app.features import KEYWORD_MONITORING_ENABLED
from app.utils.logger import bind_job_id, get_logger, restore_job_id

logger = get_logger(__name__)


async def finish_content(content_id: str, job_id: str | None = None) -> None:
    """Run the post-storage pipeline for a freshly saved Content row."""
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
    from sqlalchemy.orm import joinedload

    from app.database import SessionLocal
    from app.domains.enrich.content.summarize import apply_pipeline_summary
    from app.domains.fetch.acceptance import (
        assess_fetch_acceptance,
        ensure_listing_summary,
        stamp_fetch_acceptance_metadata,
    )
    from app.domains.fetch.finalize import hydrate_fetched_content
    from app.domains.ingest.summary_clean import apply_summary_cleaning
    from app.models import Content, Keyword
    from app.processors.content_processor import ContentProcessor
    from app.processors.keyword_matcher import KeywordMatcher
    from app.services.content_quality_service import merge_content_quality_metadata
    from app.services.scoring_service import merge_baseline_scoring_metadata

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
        content_type = (content.content_type or "").strip().lower()

        # Stage 1–2: fetch finalize (second-hop body + listing summary)
        await hydrate_fetched_content(content, source, processor=processor)

        # Stage 3: ingest (clean + keywords)
        apply_summary_cleaning(content)
        ensure_listing_summary(content)

        keyword_rows: list = []
        if KEYWORD_MONITORING_ENABLED:
            keyword_rows = db.query(Keyword).filter(Keyword.enabled == True).all()  # noqa: E712

        if KEYWORD_MONITORING_ENABLED and keyword_rows:
            matcher = KeywordMatcher()
            content.keyword_matches = matcher.match(
                content.title or "",
                content.full_content or content.summary or "",
                keyword_rows,
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

        source_stars = (source.metadata_ or {}).get("source_stars", 1) if source else 1
        accepted, accept_reason = assess_fetch_acceptance(content, meta)
        if accepted:
            meta = stamp_fetch_acceptance_metadata(meta, accepted=True, reason=accept_reason)

            # Stage 4: enrich summarize (LLM, optional)
            await apply_pipeline_summary(content)
            meta = merge_content_quality_metadata(
                meta,
                title=content.title or "",
                full_content=content.full_content,
                summary=content.summary,
                translated_summary=content.translated_summary,
            )

            # Stage 5: score (original title/summary only)
            meta = merge_baseline_scoring_metadata(
                meta,
                title=content.title or "",
                summary=content.summary,
                full_content=content.full_content,
                source_metadata=source.metadata_ if source else {},
                content_type=content_type,
                content=content,
                keyword_objects=keyword_rows if KEYWORD_MONITORING_ENABLED else None,
                keyword_matches=content.keyword_matches if KEYWORD_MONITORING_ENABLED else None,
            )
        else:
            meta = stamp_fetch_acceptance_metadata(
                meta,
                accepted=False,
                reason=accept_reason,
                source_stars=source_stars,
            )
            logger.info(
                "Fetch acceptance failed for %s (%s): %s",
                content_id,
                accept_reason,
                (content.title or "")[:60],
            )
        content.metadata_ = meta

        db.commit()
        logger.info(f"Post-processed content: {content.title[:50]}")

        if KEYWORD_MONITORING_ENABLED and content.keyword_matches:
            _dispatch_keyword_alerts(db, content)

        try:
            from app.domains.atoms import atomize_content_async

            await atomize_content_async(str(content.id))
        except Exception as exc:  # noqa: BLE001
            logger.debug("atomize_content sidecar failed for %s: %s", content_id, exc)

        try:
            from app.domains.enrich.content.listing_translation import translate_listing_fields_async

            asyncio.create_task(translate_listing_fields_async(str(content.id)))
        except Exception as exc:  # noqa: BLE001
            logger.debug("listing translation schedule failed for %s: %s", content_id, exc)

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
                pass


__all__ = [
    "finish_content",
    "_finish_content_async",
    "_dispatch_keyword_alerts",
    "logger",
]
