"""Build lightweight Content ORM objects from raw collector dicts.

This is the LLM-free portion of the fetch → ingest path: turn the
``RawItem``-shaped dicts returned by collectors into persisted-ready
:class:`Content` rows by doing local text cleanup, summary truncation,
publish-time normalisation, quality-metadata stamping, and the
``get_website_content_reject_reason`` low-signal filter.

This module is the new home for :func:`build_raw_content_objects` (Phase 3
step 3 of the module-refactor blueprint). Phase 7 retired the legacy
``app.pipeline.coordinator._build_raw_content_objects`` re-export — callers
and tests must address the canonical name here.

Internal symbols (``strip_html_tags``, ``truncate_content``,
``utcnow_naive``, ``merge_content_quality_metadata``, ``logger``) are
imported at module top so they can be monkeypatched by tests through
``app.domains.ingest.build_content.<name>`` if needed.
"""

from datetime import datetime
from typing import List

from app.models import Content, Source
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger
from app.utils.text import strip_html_tags, truncate_content
from app.domains.ingest.quality import get_website_content_reject_reason
from app.domains.ingest.quality_metadata import merge_content_quality_metadata

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
    from app.processors.extractor import ContentExtractor

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
            metadata = merge_content_quality_metadata(
                metadata,
                title=title,
                full_content=main_text_clean,
                summary=summary,
            )

            # PROACTIVE SIGNAL FILTERING
            reject_reason = get_website_content_reject_reason(
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
                    f"Pipeline: Dropping low-signal content from {source.url} ({reject_reason}): {title}"
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


__all__ = [
    "build_raw_content_objects",
    "logger",
    "strip_html_tags",
    "truncate_content",
    "utcnow_naive",
    "merge_content_quality_metadata",
    "get_website_content_reject_reason",
]
