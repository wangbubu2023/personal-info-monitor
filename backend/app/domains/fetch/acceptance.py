"""Fetch acceptance gate — body completeness is verified before value scoring.

Website/RSS rows must have title, summary, and at least partial body text.
X tweets may be short; X long articles must hydrate to full article text first.
Rows that fail acceptance are stamped ``fetch_acceptance=incomplete`` and skip scoring.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.domains.contracts.content_quality import (
    FULLTEXT_STATUS_BLOCKED,
    FULLTEXT_STATUS_FULL,
    FULLTEXT_STATUS_PARTIAL,
    FULLTEXT_STATUS_SUMMARY_ONLY,
)
from app.utils.text import strip_html_tags

_MIN_SUMMARY_CHARS = 50
_MIN_X_ARTICLE_BODY_CHARS = 280
_ACCEPTED_WEB_FULLTEXT = frozenset({
    FULLTEXT_STATUS_FULL,
    FULLTEXT_STATUS_PARTIAL,
    FULLTEXT_STATUS_SUMMARY_ONLY,
})

_FETCH_INCOMPLETE_SCORE_KEYS = (
    "final_score",
    "dimension_scores",
    "score_confidence",
    "score_version",
    "recommendation_reason",
    "domain_match",
    "scored_at",
)


def _normalize_source_stars(value: Any, default: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(3, parsed))


def is_x_long_article(content: Any, metadata: Mapping[str, Any]) -> bool:
    """True when the row represents an X long-form article, not a plain tweet."""
    from app.domains.fetch.collectors.x_twitter_text import ARTICLE_URL_RE, extract_article_urls

    content_type = (getattr(content, "content_type", None) or "").strip().lower()
    if content_type != "x":
        return False

    if str(metadata.get("x_content_type") or metadata.get("content_type") or "").strip().lower() == "article":
        return True

    candidates = [
        str(metadata.get("article_url") or ""),
        str(getattr(content, "original_url", None) or ""),
        str(getattr(content, "title", None) or ""),
        str(getattr(content, "full_content", None) or ""),
        str(getattr(content, "summary", None) or ""),
    ]
    blob = " ".join(candidates)
    if extract_article_urls(blob):
        return True
    original = str(getattr(content, "original_url", None) or "")
    return bool(ARTICLE_URL_RE.search(original))


def _listing_summary_text(content: Any) -> str:
    return strip_html_tags(getattr(content, "summary", None) or "").strip()


def ensure_listing_summary(content: Any) -> bool:
    """Derive a listing summary from body text when the fetch omitted one."""
    if len(_listing_summary_text(content)) >= _MIN_SUMMARY_CHARS:
        return False
    body = (getattr(content, "full_content", None) or "").strip()
    if len(body) < _MIN_SUMMARY_CHARS:
        return False
    preview = body[:500]
    content.summary = preview + ("..." if len(body) > 500 else "")
    return True


def _title_only_relaxed_authority(source_metadata: Mapping[str, Any] | None) -> str | None:
    source_metadata = source_metadata if isinstance(source_metadata, Mapping) else {}
    authority = str(source_metadata.get("authority_type") or "").strip().lower()
    return authority if authority in {"official", "regulator"} else None


def assess_fetch_acceptance(
    content: Any,
    metadata: Mapping[str, Any],
    *,
    source_metadata: Mapping[str, Any] | None = None,
) -> tuple[bool, str]:
    """Return ``(accepted, reason_code)`` after ingest-time body hydration."""
    metadata = metadata if isinstance(metadata, Mapping) else {}
    content_type = (getattr(content, "content_type", None) or "").strip().lower()
    title = (getattr(content, "title", None) or "").strip()
    summary = _listing_summary_text(content)
    body = (getattr(content, "full_content", None) or "").strip()
    status = str(metadata.get("fulltext_status") or "").strip()

    if content_type in {"website", "rss"}:
        if not title:
            return False, "missing_title"
        relaxed_authority = _title_only_relaxed_authority(source_metadata)
        if relaxed_authority and status == "title_only":
            return True, f"ok_relaxed_title_only_{relaxed_authority}"
        if len(summary) < _MIN_SUMMARY_CHARS:
            return False, "missing_summary"
        if status == FULLTEXT_STATUS_BLOCKED:
            return False, "blocked"
        if status not in _ACCEPTED_WEB_FULLTEXT:
            return False, f"insufficient_body_{status or 'unknown'}"
        signals = metadata.get("content_quality_signals")
        if isinstance(signals, Mapping) and status in {FULLTEXT_STATUS_FULL, FULLTEXT_STATUS_PARTIAL}:
            try:
                signal_body_len = int(signals.get("body_length") or len(body))
                signal_paragraphs = int(signals.get("paragraph_count") or 0)
            except (TypeError, ValueError):
                signal_body_len = 0
                signal_paragraphs = 0
            if signal_body_len > 1500 and signal_paragraphs <= 2:
                return False, "suspicious_flat_text"
        return True, "ok"

    if content_type == "x":
        if is_x_long_article(content, metadata):
            if len(body) < _MIN_X_ARTICLE_BODY_CHARS:
                return False, "x_article_insufficient_body"
            if not title:
                return False, "x_article_missing_title"
            if len(summary) < _MIN_SUMMARY_CHARS:
                return False, "x_article_missing_summary"
            return True, "ok"
        if not body and not title:
            return False, "x_tweet_empty"
        return True, "ok"

    if not title and not body:
        return False, "empty_content"
    return True, "ok"


def stamp_fetch_acceptance_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    accepted: bool,
    reason: str,
    source_stars: int = 1,
) -> dict[str, Any]:
    merged = dict(metadata or {})
    if accepted:
        merged["fetch_acceptance"] = "accepted"
        merged.pop("fetch_incomplete_reason", None)
        if reason.startswith("ok_relaxed_title_only_"):
            merged["acceptance_relaxed"] = reason.removeprefix("ok_relaxed_title_only_")
        else:
            merged.pop("acceptance_relaxed", None)
        return merged

    stars = _normalize_source_stars(source_stars)
    merged["fetch_acceptance"] = "incomplete"
    merged["fetch_incomplete_reason"] = reason
    merged["selection_status"] = "deferred" if stars >= 2 else "rejected"
    merged["scoring_method"] = "skipped_fetch_incomplete"
    for key in _FETCH_INCOMPLETE_SCORE_KEYS:
        merged.pop(key, None)
    return merged


__all__ = [
    "assess_fetch_acceptance",
    "ensure_listing_summary",
    "is_x_long_article",
    "stamp_fetch_acceptance_metadata",
]
