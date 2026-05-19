"""Low-signal / junk content cleanup helpers.

The "should this Content row be deleted as obvious noise" decisions
belong to the ingest domain: they re-apply the same
``get_website_content_reject_reason`` filter that the fetch path uses
on incoming raw items (``NormalizerStage`` /
``build_raw_content_objects``), plus a junk scan for embedded-binary
text fields and thin-RSS rows.

Moved out of ``app.api.contents_cleanup`` as part of Phase 3 step 7 of
the module-refactor blueprint. The FastAPI route handlers stay in
``app.api.contents_cleanup`` (HTTP routing is an interface concern),
but the pure logic — :func:`_build_low_signal_cleanup_report`,
:func:`_junk_cleanup_reason`, :func:`_content_text_blob_for_junk_scan`
— lives here so:

* the boundary ``api → pipeline`` (already gone for reject_reason
  since Phase 2.2) is reinforced by also pulling cleanup logic out of
  api,
* future Phase 5 platform-level cleanup jobs (cron) can reuse the
  helpers without importing the HTTP module.

The legacy ``app.api.contents_cleanup`` path keeps the helpers as
re-exports (route handlers import from here) so test imports like
``from app.api.contents import _build_low_signal_cleanup_report``
keep working through the existing
``api.contents → api.contents_cleanup → domains.ingest.cleanup``
chain.
"""

from __future__ import annotations

from collections import Counter

from app.domains.ingest.quality import get_website_content_reject_reason
from app.models import Content
from app.utils.text import strip_html_tags, text_looks_like_embedded_binary


def _content_text_blob_for_junk_scan(content: Content) -> str:
    return "\n".join(
        [
            content.title or "",
            content.summary or "",
            content.translated_summary or "",
            content.full_content or "",
        ]
    )


def _junk_cleanup_reason(
    content: Content,
    *,
    match_embedded_binary: bool,
    match_rss_thin_text: bool,
    rss_plain_min: int,
) -> str | None:
    """Return a machine reason if this row should be removed, else None."""
    blob = _content_text_blob_for_junk_scan(content)
    if match_embedded_binary and text_looks_like_embedded_binary(blob):
        return "embedded_binary"
    if match_rss_thin_text and content.content_type == "rss":
        ps = strip_html_tags(content.summary or "").strip()
        pf = strip_html_tags(content.full_content or "").strip()
        ts = strip_html_tags(content.translated_summary or "").strip()
        if max(len(ps), len(pf), len(ts)) < rss_plain_min:
            return "rss_thin_or_empty_text"
    return None


def _build_low_signal_cleanup_report(
    contents: list[Content],
    *,
    preview_limit: int,
) -> tuple[list[Content], dict]:
    """Re-apply the website-noise reject filter to a list of stored Content rows.

    Returns ``(matched, report)`` where ``report`` carries counts by
    reason / source plus a UI preview slice.
    """
    matched: list[Content] = []
    reason_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    preview_items: list[dict] = []

    for content in contents:
        source = content.source
        if not source:
            continue
        reason = get_website_content_reject_reason(
            source.url,
            {
                "title": content.title,
                "content": content.full_content or content.summary or "",
                "url": content.original_url,
                "html": "",
            },
        )
        if not reason:
            continue

        matched.append(content)
        source_name = source.name or "-"
        reason_counts[reason] += 1
        source_counts[source_name] += 1

        if len(preview_items) < preview_limit:
            preview_items.append(
                {
                    "id": str(content.id),
                    "reason": reason,
                    "source_id": str(source.id),
                    "source_name": source_name,
                    "title": content.title,
                    "url": content.original_url,
                    "favorited": content.favorited,
                    "archived": content.archived,
                    "read_status": content.read_status,
                    "publish_time": content.publish_time.isoformat() if content.publish_time else None,
                }
            )

    report = {
        "matched_count": len(matched),
        "by_reason": dict(sorted(reason_counts.items())),
        "by_source": dict(source_counts.most_common()),
        "preview": preview_items,
    }
    return matched, report


__all__ = [
    "_content_text_blob_for_junk_scan",
    "_junk_cleanup_reason",
    "_build_low_signal_cleanup_report",
]
