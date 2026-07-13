"""Ingest stage for normalizing and gating contents (freshness, duplicates)."""

from typing import Any, List, Tuple
import asyncio
from sqlalchemy.orm import Session

from app.models import Source, Content
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger
from app.utils.text import strip_html_tags, normalize_article_text
from app.utils.structured_article import extract_article_page_metadata, extract_structured_article
from app.utils.url import canonical_article_external_id
from app.domains.ingest.dedupe import handle_external_id_duplicate
from app.domains.ingest.quality import (
    get_non_article_format_reject_reason,
)
from app.domains.ingest.publish_time import normalize_publish_time
from app.utils.url import normalize_external_id

logger = get_logger(__name__)

# Minimum character count for an extracted article body to count as "real
# fulltext" worth backfilling over an existing stub. Mirrors the threshold
# used by :func:`app.domains.ingest.dedupe.handle_external_id_duplicate`.
_MIN_FULLTEXT_CHARS = 280


def _find_semantic_existing_content(
    db: Session,
    source_id: Any,
    title: str,
    publish_time: Any,
) -> Content | None:
    return db.query(Content).filter(
        Content.source_id == source_id,
        Content.title == title,
        Content.publish_time == publish_time,
    ).first()


def _stamp_article_page_metadata(raw_content: dict) -> None:
    html = raw_content.get("html")
    if not html:
        return
    extracted = extract_article_page_metadata(str(html), page_url=str(raw_content.get("url") or ""))
    if not extracted:
        return

    metadata = raw_content.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    canonical_url = extracted.get("canonical_url")
    if canonical_url:
        metadata["canonical_url"] = canonical_url
        metadata["canonical_external_id"] = canonical_article_external_id(str(canonical_url))

    published_time = extracted.get("published_time")
    if published_time and (not raw_content.get("publish_time") or metadata.get("publish_time_estimated")):
        raw_content["publish_time"] = published_time
        metadata["publish_time_estimated"] = False
        metadata["publish_time_source"] = "html_metadata"
        if extracted.get("published_time_raw"):
            metadata["publish_time_raw"] = str(extracted["published_time_raw"])

    raw_content["metadata"] = metadata


async def _materialize_hydrated_fulltext(raw_content: dict) -> None:
    """Pre-extract article text from hydrated HTML so the dedupe backfill path
    can upgrade pre-existing stub rows (and the new-row path can skip
    redundant re-extraction).

    The website collector's ``_hydrate_direct_articles`` stashes the article
    HTML under ``raw_content["html"]`` and blanks out ``raw_content["content"]``,
    leaving text extraction to later stages. That works for *new* rows because
    :func:`app.domains.ingest.build_content.build_raw_content_objects` extracts
    lazily — but duplicate rows go through :func:`handle_external_id_duplicate`
    first, and that helper only upgrades an existing stub when the incoming
    row already has ``content`` populated and ``metadata.article_fulltext``
    set. Without this preprocessor, every re-fetch of an existing paywall
    article throws away the hydrated HTML and the stub body stays empty.
    """
    html = raw_content.get("html")
    existing_text = str(raw_content.get("content") or "").strip()
    await asyncio.to_thread(_stamp_article_page_metadata, raw_content)
    if not html or len(existing_text) >= _MIN_FULLTEXT_CHARS:
        return

    method = "content_extractor"
    try:
        structured = await asyncio.to_thread(
            extract_structured_article,
            str(html),
            min_chars=_MIN_FULLTEXT_CHARS,
        )
        if structured:
            extracted = structured.text
            method = f"structured:{structured.method}"
        else:
            # Local import to avoid eager loading of extractor/lxml at module import.
            from app.domains.ingest.extractor import ContentExtractor

            extracted = await ContentExtractor().extract(html, raw_content.get("url"))
    except Exception as exc:  # noqa: BLE001 - extractor can raise a variety of parse errors
        logger.debug("Pre-dedupe extraction failed for %s: %s", raw_content.get("url"), exc)
        return

    clean = normalize_article_text(extracted or "").strip()
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
    metadata["article_extract_method"] = method
    raw_content["metadata"] = metadata

# Scheduled runs default to a 60-minute freshness window for real-time sources (e.g. X).
# Website/RSS/podcast/YouTube items usually carry the article/video publish time, which is
# often hours or days old — a 60m cutoff drops the entire feed (probe still looks "ok").
_FEED_ORIENTED_TYPES = frozenset({"website", "rss", "podcast", "youtube"})
_DEFAULT_SCHEDULED_MAX_LAG_FEED_LIKE_MINUTES = 10080  # 7 days, matches manual-fetch default spirit


def _append_skip_diagnostic(
    diagnostics: list[dict[str, Any]] | None,
    *,
    reason: str,
    raw_content: dict,
    detail: str | None = None,
) -> None:
    if diagnostics is None:
        return
    diagnostics.append(
        {
            "reason": reason,
            "detail": detail or "",
            "title": str(raw_content.get("title") or "").strip()[:180],
            "url": str(raw_content.get("url") or raw_content.get("external_id") or "").strip(),
        }
    )


class NormalizerStage:
    
    @staticmethod
    async def execute(
        db: Session,
        source: Source,
        raw_contents: List[dict],
        manual_trigger: bool,
        diagnostics: list[dict[str, Any]] | None = None,
    ) -> Tuple[List[dict], int]:
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
            # Cooperate with HTTP request parsing between items even when a
            # collector returned a large batch.
            await asyncio.sleep(0)
            source_type = source.type.value if hasattr(source.type, "value") else source.type

            if str(source_type).lower() == "website":
                reject_reason = get_non_article_format_reject_reason(source.url, raw_content)
                if reject_reason:
                    logger.info(
                        "Skipping non-article website content (%s): %s [%s]",
                        reject_reason,
                        str(raw_content.get("title") or "").strip(),
                        str(raw_content.get("url") or "").strip(),
                    )
                    _append_skip_diagnostic(
                        diagnostics,
                        reason="non_article_format",
                        detail=str(reject_reason),
                        raw_content=raw_content,
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
                if await asyncio.to_thread(handle_external_id_duplicate, db, source, raw_content, external_id):
                    _append_skip_diagnostic(
                        diagnostics,
                        reason="duplicate_external_id",
                        detail=external_id,
                        raw_content=raw_content,
                    )
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
                if st_lower in _FEED_ORIENTED_TYPES:
                    effective_max_lag_minutes = _DEFAULT_SCHEDULED_MAX_LAG_FEED_LIKE_MINUTES
                else:
                    interval_minutes = int(getattr(source, "fetch_interval", None) or 60)
                    effective_max_lag_minutes = max(interval_minutes * 2, 60)
                
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
                    _append_skip_diagnostic(
                        diagnostics,
                        reason="stale",
                        detail=f"{int(lag_minutes)}m>{effective_max_lag_minutes}m",
                        raw_content=raw_content,
                    )
                    continue

            # Semantic dedupe for website feeds
            raw_title = str(raw_content.get("title") or "").strip()
            if str(source_type).lower() == "website" and raw_title and publish_time:
                sem_key = (raw_title, publish_time)
                if sem_key in semantic_batch_keys:
                    logger.info("Skipping in-batch semantic-duplicate website content: %s", raw_title)
                    _append_skip_diagnostic(
                        diagnostics,
                        reason="duplicate_semantic_batch",
                        detail=str(publish_time),
                        raw_content=raw_content,
                    )
                    continue
                semantic_existing = await asyncio.to_thread(
                    _find_semantic_existing_content,
                    db,
                    source.id,
                    raw_title,
                    publish_time,
                )
                if semantic_existing:
                    logger.info("Skipping semantic-duplicate website content: %s", raw_title)
                    _append_skip_diagnostic(
                        diagnostics,
                        reason="duplicate_semantic_existing",
                        detail=str(publish_time),
                        raw_content=raw_content,
                    )
                    continue
                semantic_batch_keys.add(sem_key)

            valid_contents.append(raw_content)

        return valid_contents, stale_skipped
