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

import asyncio
from datetime import datetime, timezone
from typing import List

from app.models import Content, Source
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger
from app.utils.structured_article import extract_article_page_metadata, extract_structured_article
from app.utils.text import strip_html_tags, truncate_content, normalize_article_text
from app.utils.url import canonical_article_external_id
from app.domains.ingest.quality import (
    get_non_article_format_reject_reason,
)
from app.domains.ingest.quality_metadata import merge_content_quality_metadata
from app.domains.ingest.title_identity import merge_title_identity_metadata
from app.config import get_settings

logger = get_logger(__name__)


# A shadow candidate is normally diagnostic-only.  There is one important
# exception: when the production extractor clearly returned a truncated body
# and Web Clean has a high-confidence full article, retaining the shorter body
# is strictly worse than promoting the candidate.  Keep this gate deliberately
# conservative so a merely different extraction is not silently written.
_WEB_CLEAN_AUTO_PROMOTE_MIN_NEW_CHARS = 1200
_WEB_CLEAN_AUTO_PROMOTE_MIN_DELTA = 500
_WEB_CLEAN_AUTO_PROMOTE_MIN_SCORE = 0.85
_WEB_CLEAN_AUTO_PROMOTE_RATIO = 1.5


def _should_auto_promote_web_clean_shadow(old_text: str, clean_result) -> bool:
    """Return whether a shadow result is an unambiguous truncation repair."""
    if not clean_result or not clean_result.production_eligible():
        return False
    if clean_result.quality_status != "full":
        return False
    if float(clean_result.quality_score or 0.0) < _WEB_CLEAN_AUTO_PROMOTE_MIN_SCORE:
        return False

    old_chars = len(normalize_article_text(old_text or ""))
    new_chars = len(normalize_article_text(clean_result.article_text or ""))
    delta = new_chars - old_chars
    if new_chars < _WEB_CLEAN_AUTO_PROMOTE_MIN_NEW_CHARS or delta < _WEB_CLEAN_AUTO_PROMOTE_MIN_DELTA:
        return False
    return old_chars == 0 or new_chars >= old_chars * _WEB_CLEAN_AUTO_PROMOTE_RATIO


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
    settings = get_settings()
    results: List[Content] = []
    build_failed = 0

    for raw in raw_contents:
        await asyncio.sleep(0)
        try:
            main_text = raw.get("content", "")
            persisted_full_content: str | None = None
            html = raw.get("html")
            clean_result = None
            structured_result = None

            source_metadata = dict(source.metadata_ or {})
            web_clean_mode = str(source_metadata.get("web_clean_mode") or "shadow").strip().lower()
            if web_clean_mode not in {"off", "shadow", "write"}:
                web_clean_mode = "off"
            web_clean_write = bool(settings.pim_web_clean_enabled and web_clean_mode == "write")
            web_clean_shadow = bool(settings.pim_web_clean_shadow and web_clean_mode in {"shadow", "write"})
            web_clean_active = bool(html and source_type == "website" and (web_clean_write or web_clean_shadow))
            web_clean_promoted = False
            if web_clean_active:
                if not settings.pim_web_clean_template_enabled:
                    source_metadata.pop("web_clean_template", None)
                try:
                    clean_result = await asyncio.wait_for(
                        extractor.extract_clean(
                            str(html),
                            raw.get("url"),
                            source_id=str(source.id),
                            source_metadata=source_metadata,
                            hydrated=bool(raw.get("hydrated")),
                            max_html_bytes=settings.pim_web_clean_max_html_bytes,
                        ),
                        timeout=settings.pim_web_clean_timeout_ms / 1000,
                    )
                    from app.domains.fetch.web_clean.contracts import CleanResult

                    if not isinstance(clean_result, CleanResult):
                        clean_result = None
                except asyncio.TimeoutError:
                    logger.warning("Web clean timed out for %s", raw.get("url", "?"))
                except (ValueError, TypeError, RuntimeError) as exc:
                    logger.warning("Web clean failed for %s: %s", raw.get("url", "?"), exc)

            if web_clean_write and clean_result and clean_result.production_eligible():
                # Keep plain text for quality, summary and rejection checks, but
                # persist the canonical Markdown so Reader/export retain structure.
                main_text = clean_result.article_text
                persisted_full_content = clean_result.article_markdown or clean_result.article_text
            elif (
                web_clean_shadow
                and clean_result
                and _should_auto_promote_web_clean_shadow(main_text, clean_result)
            ):
                # Shadow mode is intentionally conservative, but a high-score
                # full candidate that is materially longer is an unambiguous
                # repair for an upstream truncated extraction.
                main_text = clean_result.article_text
                persisted_full_content = clean_result.article_markdown or clean_result.article_text
                web_clean_promoted = True
            elif html and not main_text:
                structured_result = await asyncio.to_thread(
                    extract_structured_article,
                    str(html),
                    min_chars=120,
                )
                if structured_result:
                    main_text = structured_result.text
                else:
                    main_text = await extractor.extract(html, raw.get("url"))

            main_text_clean = await asyncio.to_thread(normalize_article_text, main_text) if main_text else ""
            if persisted_full_content is None:
                persisted_full_content = main_text_clean
            title = await asyncio.to_thread(strip_html_tags, raw.get("title", "Untitled"))

            # Truncated snippet as placeholder summary (AI will replace it later)
            summary = None
            if main_text_clean:
                summary = main_text_clean[:500] + ("…" if len(main_text_clean) > 500 else "")

            metadata = raw.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            if structured_result:
                metadata = dict(metadata)
                metadata["article_fulltext"] = True
                metadata["article_extract_method"] = f"structured:{structured_result.method}"
            metadata, publish_time = await asyncio.to_thread(_merge_article_page_metadata, raw, metadata)
            if clean_result and settings.pim_web_clean_write_metadata:
                from app.domains.fetch.web_clean.shadow import build_shadow_diff

                web_clean_meta = clean_result.to_metadata(include_trace=True)
                web_clean_meta["shadow"] = not (web_clean_write or web_clean_promoted)
                web_clean_meta["source_mode"] = web_clean_mode
                if web_clean_promoted:
                    web_clean_meta["auto_promoted"] = True
                    web_clean_meta["promotion_reason"] = "high_confidence_longer_body"
                elif not web_clean_write:
                    web_clean_meta["shadow_diff"] = build_shadow_diff(main_text_clean, clean_result)
                metadata = dict(metadata)
                metadata["web_clean"] = web_clean_meta
                source_meta = dict(source.metadata_ or {})
                source_profile = {
                    key: web_clean_meta.get(key)
                    for key in (
                        "version",
                        "extraction_method",
                        "template_id",
                        "quality_status",
                        "quality_score",
                        "text_chars",
                        "paragraph_count",
                        "boilerplate_ratio",
                        "link_density",
                        "shadow",
                    )
                    if web_clean_meta.get(key) is not None
                }
                blocked_statuses = {"blocked", "login_required", "bot_wall", "captcha"}
                source_profile["blocked"] = web_clean_meta.get("quality_status") in blocked_statuses
                trace = web_clean_meta.get("trace") if isinstance(web_clean_meta.get("trace"), dict) else {}
                selected_method = trace.get("selected_method")
                candidates = trace.get("candidates") if isinstance(trace.get("candidates"), (list, tuple)) else ()
                selected_rejection = next(
                    (
                        str(item.get("rejected_reason"))[:160]
                        for item in candidates
                        if isinstance(item, dict)
                        and item.get("method") == selected_method
                        and item.get("rejected_reason")
                    ),
                    None,
                )
                template_errors = trace.get("template_validation_errors")
                recent_failure = selected_rejection
                if not recent_failure and isinstance(template_errors, (list, tuple)) and template_errors:
                    recent_failure = str(template_errors[0])[:160]
                if recent_failure:
                    source_profile["recent_failure_reason"] = recent_failure
                shadow_diff = web_clean_meta.get("shadow_diff")
                if isinstance(shadow_diff, dict):
                    source_profile["shadow_diff"] = {
                        key: shadow_diff[key]
                        for key in ("old_chars", "new_chars", "char_delta")
                        if isinstance(shadow_diff.get(key), int)
                    }
                source_meta["web_clean_profile"] = source_profile
                source.metadata_ = source_meta
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

            # High-confidence non-editorial items (slideshows, roundups, coupon
            # landing pages) can be dropped before storage. Ambiguous low-signal
            # business gating still belongs to finish-time fetch acceptance.
            reject_reason = get_non_article_format_reject_reason(
                source.url,
                {
                    "title": title,
                    "content": main_text_clean,
                    "url": raw.get("url", ""),
                    "html": html or "",
                    "ingest_channel": raw.get("ingest_channel"),
                    "metadata": metadata,
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
                full_content=(
                    truncate_content(persisted_full_content, url=raw.get("url", ""))
                    if persisted_full_content
                    else None
                ),
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
