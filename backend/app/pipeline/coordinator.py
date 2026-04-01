"""Pipeline coordinator knitting the stages together.

Fetch pipeline is deliberately lightweight: Collect → Normalize → Store raw
content, then dispatch non-blocking per-item post-processing tasks. This keeps
fetch workers free and maximises fetch throughput.
"""

from datetime import datetime
from typing import Dict, Any, List

from sqlalchemy.orm import Session

from app.models import Content, Source
from app.utils.datetime import utcnow_naive
from app.utils.text import strip_html_tags, truncate_content
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def _build_raw_content_objects(raw_contents: List[dict], source: Source) -> List[Content]:
    """Build Content ORM objects from raw dicts without any LLM calls.

    Only does local text extraction / cleanup so the fetch task stays fast.
    Keyword matching / optional cookie full-text enrichment happen
    asynchronously via ``process_new_content``.
    """
    from app.processors.extractor import ContentExtractor

    extractor = ContentExtractor()
    source_type = source.type.value if hasattr(source.type, "value") else str(source.type)
    results: List[Content] = []

    for raw in raw_contents:
        try:
            main_text = raw.get("content", "")
            html = raw.get("html")

            if html and not main_text:
                main_text = await extractor.extract(html, raw.get("url"))

            main_text_clean = strip_html_tags(main_text) if main_text else ""
            title = strip_html_tags(raw.get("title", "Untitled"))

            # Truncated snippet as placeholder summary (AI will replace it later)
            summary = None
            if main_text_clean:
                summary = main_text_clean[:500] + ("…" if len(main_text_clean) > 500 else "")

            publish_time = raw.get("publish_time")
            if isinstance(publish_time, str):
                try:
                    publish_time = datetime.fromisoformat(publish_time.replace("Z", "+00:00"))
                except Exception:
                    publish_time = utcnow_naive()
            elif not publish_time:
                publish_time = utcnow_naive()

            metadata = raw.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}

            results.append(Content(
                source_id=source.id,
                external_id=raw.get("external_id"),
                title=title,
                summary=summary,
                original_url=raw.get("url", ""),
                content_type=source_type,
                publish_time=publish_time,
                full_content=truncate_content(main_text_clean, url=raw.get("url", "")) if main_text_clean else None,
                metadata_=metadata,
                keyword_matches=[],
                fetched_at=utcnow_naive(),
            ))
        except Exception as exc:
            logger.error(f"Failed to build Content object for {raw.get('url', '?')}: {exc}")
            continue

    return results


def _update_source_status(
    source: Source,
    merged_warning: str | None,
    primary_warning: tuple | None,
    code: str,
    severity: str,
    message: str,
):
    """Centralised helper to update source metadata after a fetch attempt."""
    from app.tasks.fetch_orchestrator import set_last_fetch_outcome

    source.last_fetched_at = utcnow_naive()
    source.last_error = merged_warning
    if primary_warning and primary_warning[1] == "error":
        source.error_count = (source.error_count or 0) + 1
        set_last_fetch_outcome(source, primary_warning[0], "error", merged_warning or primary_warning[2])
    elif primary_warning:
        source.error_count = 0
        set_last_fetch_outcome(source, primary_warning[0], "warning", merged_warning or primary_warning[2])
    else:
        source.error_count = 0
        set_last_fetch_outcome(source, code, severity, message)


def _apply_keyword_filter(db: Session, source: Source, content_objects: list[Content]) -> tuple[list[Content], int]:
    """Filter content objects by enabled keywords. Returns (kept, filtered_count)."""
    from app.models import Keyword
    from app.processors.keyword_matcher import KeywordMatcher

    keywords = db.query(Keyword).filter(Keyword.enabled == True).all()
    if not keywords:
        # No keywords configured = pass everything through
        logger.warning("Source %s has keyword filter enabled but no keywords configured", source.name)
        return content_objects, 0

    matcher = KeywordMatcher()
    kept = []
    for content in content_objects:
        search_text = f"{content.title or ''} {content.full_content or content.summary or ''}"
        matches = matcher.match(search_text, keywords)
        if matches:
            content.keyword_matches = matches
            kept.append(content)

    filtered_count = len(content_objects) - len(kept)
    if filtered_count > 0:
        logger.info(
            "Keyword filter for %s: %d/%d items passed (%d filtered)",
            source.name, len(kept), len(content_objects), filtered_count,
        )
    return kept, filtered_count


async def run_fetch_pipeline(db: Session, source: Source, manual_trigger: bool = False) -> Dict[str, Any]:
    """Run the fetch pipeline for a source.

    Flow: Collect → Normalise → Store raw → dispatch post-processing tasks (async).
    """
    # Import stages lazily to avoid circular import (fetch_tasks → coordinator → collector → … → fetch_tasks).
    from app.pipeline.collector_stage import CollectorStage
    from app.pipeline.normalizer_stage import NormalizerStage
    from app.pipeline.storage_stage import StorageStage

    # 1. Collector Stage
    raw_contents, merged_warning, primary_warning = await CollectorStage.execute(db, source)

    if not raw_contents:
        logger.info(f"No new content from source: {source.name}")
        _update_source_status(source, merged_warning, primary_warning,
                              "no_new_content", "info", "最近抓取完成但暂无新内容")
        db.commit()
        if primary_warning:
            level = "error" if primary_warning[1] == "error" else "warning"
            return {"status": level, "message": merged_warning or primary_warning[2], "count": 0}
        return {"status": "success", "message": "No new content", "count": 0}

    # 2. Normalizer Stage (freshness, semantic dedupe, backfill)
    valid_raw_contents, stale_skipped = await NormalizerStage.execute(db, source, raw_contents, manual_trigger)

    if not valid_raw_contents:
        logger.info(f"All content already fetched from: {source.name}")
        _update_source_status(source, merged_warning, primary_warning,
                              "up_to_date", "info", "内容已是最新")
        db.commit()
        if primary_warning:
            level = "error" if primary_warning[1] == "error" else "warning"
            return {"status": level, "message": merged_warning or primary_warning[2], "count": 0}
        return {"status": "success", "message": "All content up to date", "count": 0}

    # 3. Build lightweight Content objects (no LLM) and persist
    content_objects = await _build_raw_content_objects(valid_raw_contents, source)
    keyword_filtered_count = 0
    if getattr(source, "use_keyword_filter", False):
        content_objects, keyword_filtered_count = _apply_keyword_filter(db, source, content_objects)
        if not content_objects:
            logger.info(f"All {keyword_filtered_count} items filtered out by keywords for: {source.name}")
            _update_source_status(source, merged_warning, primary_warning,
                                  "keyword_filtered", "info", f"抓取到 {keyword_filtered_count} 条内容，均不匹配关键词")
            db.commit()
            return {
                "status": "success",
                "message": f"All {keyword_filtered_count} items filtered by keywords",
                "count": 0,
                "keyword_filtered": keyword_filtered_count,
            }

    saved_count, latest_saved_marker = StorageStage.execute(db, content_objects)

    # 4. Update source metadata
    if latest_saved_marker:
        marker = latest_saved_marker[:255] if len(latest_saved_marker) > 255 else latest_saved_marker
        source.last_content_id = marker
    elif not db.query(Content.id).filter(Content.source_id == source.id).first():
        source.last_content_id = None

    _update_source_status(source, merged_warning, primary_warning,
                          "ok", "info", "抓取成功")
    db.commit()

    # 5. Collect new content IDs for async post-processing
    new_content_ids = [str(c.id) for c in content_objects if c.id]

    logger.info(
        f"Fetched {len(raw_contents)} items from {source.name}, "
        f"saved={saved_count}, stale_skipped={stale_skipped}"
    )
    return {
        "status": "success",
        "count": len(raw_contents),
        "saved": saved_count,
        "stale_skipped": stale_skipped,
        "keyword_filtered": keyword_filtered_count,
        "new_content_ids": new_content_ids,
    }
