"""Build lightweight Content ORM objects from raw collector dicts.

This is the LLM-free portion of the fetch -> ingest path: turn the
raw dicts returned by collectors into persisted-ready
:class:`Content` rows by doing local text cleanup, summary truncation,
publish-time normalisation, quality-metadata stamping, and the
``get_non_article_format_reject_reason`` hard non-article format filter.

This module is the new home for :func:`build_raw_content_objects` (Phase 3
step 3 of the module-refactor blueprint). The fetch coordinator imports this
canonical helper directly; callers and tests should address the canonical
name here.

Internal symbols (``strip_html_tags``, ``truncate_content``,
``utcnow_naive``, ``merge_content_quality_metadata``, ``logger``) are
imported at module top so they can be monkeypatched by tests through
``app.domains.ingest.build_content.<name>`` if needed.
"""

from datetime import datetime, timezone
from typing import List

from app.models import Content, Source
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger
from app.utils.structured_article import extract_article_page_metadata
from app.utils.text import strip_html_tags, truncate_content, normalize_article_text
from app.utils.url import canonical_article_external_id
from app.domains.ingest.quality import (
    get_non_article_format_reject_reason,
)
from app.domains.ingest.quality_metadata import merge_content_quality_metadata
from app.domains.ingest.title_identity import merge_title_identity_metadata

logger = get_logger(__name__)


async def build_raw_content_objects(
    raw_contents: List[dict],
    source: Source,
) -> tuple[List[Content], int]:
    """Build Content ORM objects from raw dicts without any LLM calls.

    Only does local text extraction / cleanup so the fetch task stays fast.
    Keyword matching / optional cookie full-text enrichment happen
    asynchronously via :func:`app.domains.ingest.finish.finish_content`.
    """
    # Local import keeps lxml / readability off the import graph until the
    # first real fetch hits a Content build.
    from app.domains.ingest.extractor import ContentExtractor

    extractor = ContentExtractor()
    source_type = source.type.value if hasattr(source.type, "value") else str(source.type)
    results: List[Content] = []
    build_failed = 0

    for raw in raw_contents:
        try:
            main_text = raw.get("content", "")
            html = raw.get("html")

            if html and not main_text:
                main_text = await extractor.extract(html, raw.get("url"))

            main_text_clean = normalize_article_text(main_text) if main_text else ""
            title = strip_html_tags(raw.get("title", "Untitled"))

            # Truncated snippet as placeholder summary (AI will replace it later)
            summary = None
            if main_text_clean:
                summary = main_text_clean[:500] + ("…" if len(main_text_clean) > 500 else "")

            metadata = raw.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            metadata, publish_time = _merge_article_page_metadata(raw, metadata)
            if isinstance(publish_time, str):
                try:
                    publish_time = datetime.fromisoformat(publish_time.replace("Z", "+00:00"))
                    if publish_time.tzinfo is not None:
                        publish_time = publish_time.astimezone(timezone.utc).replace(tzinfo=None)
                except Exception:
                    publish_time = None
            metadata = merge_content_quality_metadata(
                metadata,
                title=title,
                full_content=main_text_clean,
                summary=summary,
            )
            metadata = merge_title_identity_metadata(metadata, title=title)

            # Slideshows/galleries/roundups are format-level non-articles and
            # can be dropped before storage. Low-signal business gating belongs
            # to finish-time fetch acceptance so incomplete rows are observable.
            reject_reason = get_non_article_format_reject_reason(
                source.url,
                {
                    "title": title,
                    "content": main_text_clean,
                    "url": raw.get("url", ""),
                    "html": html or "",
                },
            )
            if reject_reason:
                logger.info(
                    f"Pipeline: Dropping non-article content from {source.url} ({reject_reason}): {title}"
                )
                continue

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
            build_failed += 1
            logger.error(f"Failed to build Content object for {raw.get('url', '?')}: {exc}")
            continue

    return results, build_failed


def _merge_article_page_metadata(raw: dict, metadata: dict) -> tuple[dict, object]:
    """Merge canonical/publish metadata extracted from already-fetched HTML."""
    html = raw.get("html")
    publish_time = raw.get("publish_time")
    if not html:
        return metadata, publish_time

    extracted = extract_article_page_metadata(str(html), page_url=str(raw.get("url") or ""))
    if not extracted:
        return metadata, publish_time

    merged = dict(metadata)
    canonical_url = extracted.get("canonical_url")
    if canonical_url:
        merged["canonical_url"] = canonical_url
        merged["canonical_external_id"] = canonical_article_external_id(str(canonical_url))

    published_time = extracted.get("published_time")
    if published_time and (not publish_time or merged.get("publish_time_estimated")):
        publish_time = published_time
        merged["publish_time_estimated"] = False
        merged["publish_time_source"] = "html_metadata"
        if extracted.get("published_time_raw"):
            merged["publish_time_raw"] = str(extracted["published_time_raw"])
    return merged, publish_time


__all__ = [
    "build_raw_content_objects",
    "logger",
    "strip_html_tags",
    "truncate_content",
    "utcnow_naive",
    "merge_content_quality_metadata",
    "get_non_article_format_reject_reason",
]
