"""Post-fetch pipeline orchestration — fetch hydrate → ingest → summarize → score.

``finish_content`` is the single enqueue target after storage. It runs seven
pipeline stages (see MODULE_BOUNDARIES.md); only stages 4–5 may invoke LLM.
"""

from __future__ import annotations

import asyncio

from app.background import get_finalize_semaphore, get_llm_semaphore, task_tracker  # noqa: F401
from app.features import ATOMS_PRODUCT_ENABLED, KEYWORD_MONITORING_ENABLED
from app.utils.logger import bind_job_id, get_logger, restore_job_id

logger = get_logger(__name__)


async def finish_content(content_id: str, job_id: str | None = None) -> None:
    """Run the post-storage pipeline for a freshly saved Content row."""
    token = bind_job_id(job_id) if job_id else None
    try:
        sem = get_finalize_semaphore()
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
    from app.domains.ingest.quality_metadata import merge_content_quality_metadata
    from app.domains.ingest.failures import ContentNotFoundError
    from app.domains.ingest.summary_clean import apply_summary_cleaning
    from app.domains.score.content_columns import sync_content_score_columns
    from app.domains.score.scoring import merge_rule_scoring_metadata_async
    from app.models import Content, Keyword, Source
    from app.domains.ingest.content_processor import ContentProcessor
    from app.domains.ingest.keywords.matcher import KeywordMatcher

    # Session construction is cheap, but its first query checks out a
    # synchronous SQLite connection. Do both in a worker thread so four
    # post-process workers cannot stall the HTTP event loop together.
    def _load_content():
        loaded_db = SessionLocal()
        loaded_db.expire_on_commit = False
        try:
            loaded_content = (
                loaded_db.query(Content)
                .options(joinedload(Content.source).joinedload(Source.auth_config))
                .filter(Content.id == content_id)
                .first()
            )
            return loaded_db, loaded_content
        except Exception:
            loaded_db.close()
            raise

    db, content = await asyncio.to_thread(_load_content)
    # The rest of this function contains network and optional LLM awaits.
    # Keep loaded ORM state alive, but release the SQLite connection before
    # those awaits so one slow item cannot reserve a sync-pool slot for minutes.
    try:
        if not content:
            logger.error("Content not found: %s", content_id)
            raise ContentNotFoundError(content_id)

        await asyncio.to_thread(db.commit)

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
            keyword_rows = await asyncio.to_thread(
                lambda: db.query(Keyword).filter(Keyword.enabled == True).all()  # noqa: E712
            )

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
        accepted, accept_reason = assess_fetch_acceptance(
            content,
            meta,
            source_metadata=source.metadata_ if source else {},
        )
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
            meta = await merge_rule_scoring_metadata_async(
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
            meta.pop("personalization", None)
        else:
            if accept_reason == "suspicious_flat_text":
                rejected_body_len = len((content.full_content or "").strip())
                if rejected_body_len:
                    content.full_content = None
                    meta["rejected_full_content_reason"] = accept_reason
                    meta["rejected_full_content_chars"] = rejected_body_len
                    meta.pop("article_fulltext", None)
                    meta.pop("article_text_chars", None)
                    meta = merge_content_quality_metadata(
                        meta,
                        title=content.title or "",
                        full_content=content.full_content,
                        summary=content.summary,
                        translated_summary=content.translated_summary,
                    )
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
        sync_content_score_columns(content, meta)

        await asyncio.to_thread(db.commit)
        logger.info(f"Post-processed content: {content.title[:50]}")

        # Event assignment is no longer coupled to the hourly Brief. It runs as
        # an idempotent stage of the existing durable postprocess job so worker
        # crashes/retries cannot lose an accepted Content row. v1 writes remain
        # shadow-only until the separately gated Today read switch is approved.
        if accepted:
            from app.domains.events.engine import assign_content_sync

            await asyncio.to_thread(assign_content_sync, str(content.id), shadow_only=True)

        if KEYWORD_MONITORING_ENABLED and content.keyword_matches:
            await _dispatch_keyword_alerts_async(db, content)
            # Alert preference resolution performs read-only lookups. End that
            # transaction before any subsequent async sidecar work.
            await asyncio.to_thread(db.rollback)

        if ATOMS_PRODUCT_ENABLED:
            try:
                from app.domains.atoms import atomize_content_async

                await atomize_content_async(str(content.id))
            except Exception as exc:  # noqa: BLE001
                logger.debug("atomize_content sidecar failed for %s: %s", content_id, exc)

        try:
            from app.domains.enrich.content.listing_translation import enqueue_listing_translation_job

            await enqueue_listing_translation_job(
                str(content.id),
                title=content.title or "",
                summary=content.summary,
                translated_title=content.translated_title,
                translated_summary=content.translated_summary,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("listing translation schedule failed for %s: %s", content_id, exc)

    except Exception:
        await asyncio.to_thread(db.rollback)
        logger.exception("finish_content failed for %s", content_id)
        raise
    finally:
        await asyncio.to_thread(db.close)


def _notifiable_keyword_names(db, content) -> list[str]:
    from app.models import Keyword

    names: list[str] = []
    for match in content.keyword_matches:
        keyword_obj = db.query(Keyword).filter(Keyword.id == match["id"]).first()
        if keyword_obj and keyword_obj.notify:
            names.append(str(match["keyword"]))
    return names


def _schedule_keyword_alerts(content, keyword_names: list[str]) -> None:
    from app.domains.enrich.notifications.keyword_alert import send_keyword_alert

    async def _deliver_keyword_alert(keyword: str) -> None:
        try:
            await send_keyword_alert(str(content.id), keyword, content.title)
        except Exception as exc:
            logger.warning("Keyword alert dispatch failed for %s: %s", content.id, exc)

    for keyword in keyword_names:
        try:
            asyncio.create_task(_deliver_keyword_alert(keyword))
        except RuntimeError:
            pass


def _dispatch_keyword_alerts(db, content) -> None:
    """Schedule keyword-alert emails fire-and-forget (sync compatibility API)."""
    _schedule_keyword_alerts(content, _notifiable_keyword_names(db, content))


async def _dispatch_keyword_alerts_async(db, content) -> None:
    """Resolve notification preferences without blocking uvicorn's loop."""
    keyword_names = await asyncio.to_thread(_notifiable_keyword_names, db, content)
    _schedule_keyword_alerts(content, keyword_names)


__all__ = [
    "finish_content",
    "_finish_content_async",
    "_dispatch_keyword_alerts",
    "logger",
]
