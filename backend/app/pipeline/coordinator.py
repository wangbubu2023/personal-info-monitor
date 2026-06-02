"""Pipeline coordinator knitting the stages together.

Fetch pipeline is deliberately lightweight: Collect → Normalize → Store raw
content, then dispatch non-blocking per-item post-processing tasks. This keeps
fetch workers free and maximises fetch throughput.
"""

from typing import Dict, Any

from sqlalchemy.orm import Session

from app.models import Content, Source
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger
from app.domains.ingest.build_content import build_raw_content_objects

logger = get_logger(__name__)

__all__ = [
    "run_fetch_pipeline",
    "_update_source_status",
    "_apply_keyword_filter",
    "logger",
]


def _record_fetch_profile(
    source: Source,
    *,
    outcome: str,
    eff_code: str,
    severity: str = "error",
    saved_count: int,
    latency_ms: float | None,
) -> None:
    """Best-effort: fold this attempt into the rolling fetch profile + cooldown.

    Wrapped in a broad ``except`` because profiling/cooldown bookkeeping must
    never break the fetch path — a malformed metadata blob should degrade to
    "no profile" rather than fail the whole pipeline.
    """
    try:
        from app.domains.fetch.profile import record_fetch_result
        from app.domains.fetch.retry_policy import clear_fetch_failure, record_fetch_failure

        if outcome == "failure":
            record_fetch_failure(source, code=eff_code, severity=severity)
        else:
            clear_fetch_failure(source)

        record_fetch_result(
            source,
            outcome=outcome,  # type: ignore[arg-type]
            saved_count=saved_count,
            latency_ms=latency_ms,
            failure_code=eff_code if outcome == "failure" else None,
        )
    except Exception as exc:  # noqa: BLE001 — profiling is non-critical
        logger.debug("Fetch profile/cooldown bookkeeping failed for %s: %s", source.name, exc)


def _update_source_status(
    source: Source,
    merged_warning: str | None,
    primary_warning: tuple | None,
    code: str,
    severity: str,
    message: str,
    *,
    saved_count: int = 0,
    latency_ms: float | None = None,
):
    """Centralised helper to update source metadata after a fetch attempt."""
    from app.domains.sources.status import set_last_fetch_outcome

    source.last_fetched_at = utcnow_naive()
    source.last_error = merged_warning
    if primary_warning and primary_warning[1] == "error":
        eff_code = primary_warning[0]
        source.error_count = (source.error_count or 0) + 1
        set_last_fetch_outcome(source, eff_code, "error", merged_warning or primary_warning[2])
        _record_fetch_profile(
            source,
            outcome="failure",
            eff_code=eff_code,
            severity="error",
            saved_count=0,
            latency_ms=latency_ms,
        )
        from app.config import get_settings

        th = int(get_settings().fetch_error_disable_threshold or 0)
        if th > 0 and (source.error_count or 0) >= th and source.enabled:
            source.enabled = False
            suffix = " [auto-disabled after repeated fetch errors — re-enable in Sources when fixed]"
            base = (merged_warning or primary_warning[2] or "").strip()
            source.last_error = (base + suffix)[:4000]
            logger.warning(
                "Auto-disabled source %s (id=%s) after error_count=%s (>=%s)",
                source.name,
                source.id,
                source.error_count,
                th,
            )
    elif primary_warning:
        source.error_count = 0
        eff_code = primary_warning[0]
        set_last_fetch_outcome(source, eff_code, "warning", merged_warning or primary_warning[2])
        from app.domains.fetch.retry_policy import cooldown_seconds_for_code

        outcome = "failure" if cooldown_seconds_for_code(eff_code) else ("success" if saved_count > 0 else "empty")
        _record_fetch_profile(
            source,
            outcome=outcome,
            eff_code=eff_code,
            severity="warning",
            saved_count=saved_count,
            latency_ms=latency_ms,
        )
    else:
        source.error_count = 0
        set_last_fetch_outcome(source, code, severity, message)
        outcome = "success" if saved_count > 0 else "empty"
        _record_fetch_profile(
            source,
            outcome=outcome,
            eff_code=code,
            severity=severity,
            saved_count=saved_count,
            latency_ms=latency_ms,
        )


def _apply_keyword_filter(db: Session, source: Source, content_objects: list[Content]) -> tuple[list[Content], int]:
    """Filter content objects by enabled keywords. Returns (kept, filtered_count)."""
    from app.models import Keyword
    from app.processors.keyword_matcher import KeywordMatcher

    keywords = db.query(Keyword).filter(Keyword.enabled == True).all()
    if not keywords:
        # No keywords configured but filter enabled = block everything
        logger.warning("Source %s has keyword filter enabled but no keywords configured; rejecting all", source.name)
        return [], len(content_objects)

    matcher = KeywordMatcher()
    kept = []
    for content in content_objects:
        matches = matcher.match(
            content.title or "",
            content.full_content or content.summary or "",
            keywords,
        )
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
    import time

    from app.pipeline.collector_stage import CollectorStage
    from app.domains.ingest.normalizer import NormalizerStage
    from app.domains.ingest.storage import StorageStage

    started_at = time.monotonic()

    def _elapsed_ms() -> float:
        return (time.monotonic() - started_at) * 1000.0

    # 1. Collector Stage
    raw_contents, merged_warning, primary_warning = await CollectorStage.execute(db, source)

    if not raw_contents:
        logger.info(f"No new content from source: {source.name}")
        _update_source_status(source, merged_warning, primary_warning,
                              "no_new_content", "info", "最近抓取完成但暂无新内容",
                              latency_ms=_elapsed_ms())
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
                              "up_to_date", "info", "内容已是最新",
                              latency_ms=_elapsed_ms())
        db.commit()
        if primary_warning:
            level = "error" if primary_warning[1] == "error" else "warning"
            return {"status": level, "message": merged_warning or primary_warning[2], "count": 0}
        return {"status": "success", "message": "All content up to date", "count": 0}

    # 3. Build lightweight Content objects (no LLM) and persist
    content_objects, build_failed = await build_raw_content_objects(valid_raw_contents, source)
    keyword_filtered_count = 0
    if getattr(source, "use_keyword_filter", False):
        content_objects, keyword_filtered_count = _apply_keyword_filter(db, source, content_objects)
        if not content_objects:
            logger.info(f"All {keyword_filtered_count} items filtered out by keywords for: {source.name}")
            _update_source_status(source, merged_warning, primary_warning,
                                  "keyword_filtered", "info", f"抓取到 {keyword_filtered_count} 条内容，均不匹配关键词",
                                  latency_ms=_elapsed_ms())
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
                          "ok", "info", "抓取成功",
                          saved_count=saved_count, latency_ms=_elapsed_ms())
    db.commit()

    # 5. Collect new content IDs for async post-processing
    new_content_ids = [str(c.id) for c in content_objects if c.id]

    logger.info(
        "Fetched %s items from %s, saved=%s, stale_skipped=%s, build_failed=%s",
        len(raw_contents),
        source.name,
        saved_count,
        stale_skipped,
        build_failed,
    )
    return {
        "status": "success",
        "count": len(raw_contents),
        "saved": saved_count,
        "stale_skipped": stale_skipped,
        "build_failed": build_failed,
        "keyword_filtered": keyword_filtered_count,
        "new_content_ids": new_content_ids,
    }
