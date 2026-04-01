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

from app.pipeline.collector_stage import CollectorStage
from app.pipeline.normalizer_stage import NormalizerStage
from app.pipeline.storage_stage import StorageStage
from app.tasks.fetch_orchestrator import set_last_fetch_outcome

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


async def run_fetch_pipeline(db: Session, source: Source, manual_trigger: bool = False) -> Dict[str, Any]:
    """Run the fetch pipeline for a source.

    Flow: Collect → Normalise → Store raw → dispatch post-processing tasks (async).
    """
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
        "new_content_ids": new_content_ids,
    }
