"""Pipeline stage for normalizing and gating contents (freshness, duplicates)."""

from typing import List, Tuple
from sqlalchemy.orm import Session

from app.models import Source, Content
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger
from app.utils.text import strip_html_tags
from app.domains.ingest.quality import get_website_content_reject_reason
from app.pipeline.dedupe import handle_external_id_duplicate
from app.pipeline.utils import (
    normalize_external_id,
    normalize_publish_time,
)

logger = get_logger(__name__)

# Minimum character count for an extracted article body to count as "real
# fulltext" worth backfilling over an existing stub. Mirrors the threshold
# used by :func:`app.pipeline.dedupe.handle_external_id_duplicate`.
_MIN_FULLTEXT_CHARS = 280


async def _materialize_hydrated_fulltext(raw_content: dict) -> None:
    """Pre-extract article text from hydrated HTML so the dedupe backfill path
    can upgrade pre-existing stub rows (and the new-row path can skip
    redundant re-extraction).

    The website collector's ``_hydrate_direct_articles`` stashes the article
    HTML under ``raw_content["html"]`` and blanks out ``raw_content["content"]``,
    leaving text extraction to later stages. That works for *new* rows because
    :func:`app.pipeline.coordinator._build_raw_content_objects` extracts
    lazily — but duplicate rows go through :func:`handle_external_id_duplicate`
    first, and that helper only upgrades an existing stub when the incoming
    row already has ``content`` populated and ``metadata.article_fulltext``
    set. Without this preprocessor, every re-fetch of an existing paywall
    article throws away the hydrated HTML and the stub body stays empty.
    """
    html = raw_content.get("html")
    existing_text = str(raw_content.get("content") or "").strip()
    if not html or len(existing_text) >= _MIN_FULLTEXT_CHARS:
        return

    # Local import to avoid eager loading of extractor/lxml at module import.
    from app.processors.extractor import ContentExtractor

    try:
        extracted = await ContentExtractor().extract(html, raw_content.get("url"))
    except Exception as exc:  # noqa: BLE001 - extractor can raise a variety of parse errors
        logger.debug("Pre-dedupe extraction failed for %s: %s", raw_content.get("url"), exc)
        return

    clean = strip_html_tags(extracted or "").strip()
    if len(clean) < _MIN_FULLTEXT_CHARS:
        logger.debug(
            "Hydrated-html extraction too short for %s: html=%d extracted=%d clean=%d < %d",
            raw_content.get("url"),
            len(html),
            len(extracted or ""),
            len(clean),
            _MIN_FULLTEXT_CHARS,
        )
        return
    logger.debug(
        "Hydrated-html fulltext ready for %s: html=%d clean=%d chars",
        raw_content.get("url"),
        len(html),
        len(clean),
    )

    raw_content["content"] = clean
    metadata = raw_content.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata["article_fulltext"] = True
    raw_content["metadata"] = metadata

# Scheduled runs default to a 60-minute freshness window for real-time sources (e.g. X).
# Website/RSS/podcast/YouTube items usually carry the article/video publish time, which is
# often hours or days old — a 60m cutoff drops the entire feed (probe still looks "ok").
_FEED_ORIENTED_TYPES = frozenset({"website", "rss", "podcast", "youtube"})
_DEFAULT_SCHEDULED_MAX_LAG_FEED_LIKE_MINUTES = 10080  # 7 days, matches manual-fetch default spirit


class NormalizerStage:
    
    @staticmethod
    async def execute(db: Session, source: Source, raw_contents: List[dict], manual_trigger: bool) -> Tuple[List[dict], int]:
        """
        Execute the normalizer stage.
        Filters out contents that are duplicate in DB or too stale.
        Returns:
            Tuple containing:
            - List of valid raw content dicts to process further
            - Integer count of skipped stale items
        """
        valid_contents = []
        stale_skipped = 0
        semantic_batch_keys: set[tuple[str, object]] = set()

        for raw_content in raw_contents:
            source_type = source.type.value if hasattr(source.type, "value") else source.type

            if str(source_type).lower() == "website":
                reject_reason = get_website_content_reject_reason(source.url, raw_content)
                if reject_reason:
                    logger.info(
                        "Skipping low-signal website content (%s): %s [%s]",
                        reject_reason,
                        str(raw_content.get("title") or "").strip(),
                        str(raw_content.get("url") or "").strip(),
                    )
                    continue

            # If the collector hydrated the article HTML for us (paywall sites,
            # direct-article mode), extract the body text up-front so the dedupe
            # backfill path can upgrade any existing stub row, not just brand-new
            # entries. No-op when ``html`` is absent or ``content`` is already set.
            await _materialize_hydrated_fulltext(raw_content)

            # Check for duplicates before processing
            external_id = normalize_external_id(raw_content.get("external_id"))
            if external_id:
                raw_content["external_id"] = external_id
                if handle_external_id_duplicate(db, source, raw_content, external_id):
                    continue
            
            # Freshness gate: (now - publish_time) must be <= threshold (minutes).
            # Per-source override: source.metadata["max_fetch_lag_minutes"] (UI: 抓取回溯时间).
            metadata = source.metadata_ or {}
            configured_max_lag = metadata.get("max_fetch_lag_minutes")
            
            if manual_trigger:
                effective_max_lag_minutes = int(configured_max_lag) if configured_max_lag is not None else 10080
            elif configured_max_lag is not None:
                effective_max_lag_minutes = int(configured_max_lag)
            else:
                st_lower = str(source_type).lower()
                effective_max_lag_minutes = (
                    _DEFAULT_SCHEDULED_MAX_LAG_FEED_LIKE_MINUTES
                    if st_lower in _FEED_ORIENTED_TYPES
                    else 60
                )
                
            publish_time = await normalize_publish_time(raw_content, str(source_type))
            if publish_time:
                raw_content["publish_time"] = publish_time
                lag_minutes = (utcnow_naive() - publish_time).total_seconds() / 60
                if lag_minutes > effective_max_lag_minutes:
                    stale_skipped += 1
                    logger.info(
                        f"Skipping stale content ({int(lag_minutes)}m>{effective_max_lag_minutes}m): "
                        f"{raw_content.get('url', '')}"
                    )
                    continue

            # Semantic dedupe for website feeds
            raw_title = str(raw_content.get("title") or "").strip()
            if str(source_type).lower() == "website" and raw_title and publish_time:
                sem_key = (raw_title, publish_time)
                if sem_key in semantic_batch_keys:
                    logger.info("Skipping in-batch semantic-duplicate website content: %s", raw_title)
                    continue
                semantic_existing = db.query(Content).filter(
                    Content.source_id == source.id,
                    Content.title == raw_title,
                    Content.publish_time == publish_time,
                ).first()
                if semantic_existing:
                    logger.info("Skipping semantic-duplicate website content: %s", raw_title)
                    continue
                semantic_batch_keys.add(sem_key)

            valid_contents.append(raw_content)

        return valid_contents, stale_skipped
