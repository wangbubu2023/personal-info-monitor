"""Publish-time normalization helpers for ingest freshness checks."""

from __future__ import annotations

from datetime import datetime, timezone

from app.utils.logger import get_logger

logger = get_logger(__name__)


def _parse_iso_publish_time(value: str) -> datetime | None:
    """Parse an ISO-8601 publish time string, tolerating the ``Z`` UTC suffix."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError as exc:
        logger.debug("Discarding malformed ISO publish_time %r: %s", value, exc)
        return None


async def resolve_website_publish_time(raw_content: dict) -> datetime | None:
    """Resolve publish_time for website content with fallback to article page extraction."""
    publish_time = raw_content.get("publish_time")
    if isinstance(publish_time, str):
        parsed = _parse_iso_publish_time(publish_time)
        if parsed is not None:
            return parsed
        publish_time = None

    if isinstance(publish_time, datetime):
        return publish_time

    metadata = raw_content.get("metadata") or {}
    if metadata.get("publish_time_estimated"):
        url = raw_content.get("url")
        if url:
            from app.utils.publish_time import fetch_publish_time_from_url

            return await fetch_publish_time_from_url(url)
    return None


async def normalize_publish_time(raw_content: dict, source_type: str) -> datetime | None:
    """Normalize publish_time from raw content for freshness checks."""
    if source_type == "website":
        return await resolve_website_publish_time(raw_content)

    publish_time = raw_content.get("publish_time")
    if isinstance(publish_time, str):
        return _parse_iso_publish_time(publish_time)
    if isinstance(publish_time, datetime):
        return publish_time
    return None


__all__ = [
    "normalize_publish_time",
    "resolve_website_publish_time",
]
