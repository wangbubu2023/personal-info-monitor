"""Pipeline utility functions.

.. deprecated::
    ``get_website_content_reject_reason`` (and the constants /
    helpers backing it) moved to :mod:`app.domains.ingest.quality`
    as part of Phase 2/3 of the module refactor. This module keeps
    a re-export so existing ``unittest.mock.patch`` targets and
    ``from app.pipeline.utils import …`` callers continue to work;
    new code SHOULD import from the new home.
"""

import hashlib
from datetime import datetime
from typing import List
from urllib.parse import urlparse

from app.domains.ingest.quality import (  # noqa: F401 — re-export
    _DOMAIN_NON_ARTICLE_PATH_SEGMENTS,
    _DOMAIN_WEBSITE_SECTION_TITLES,
    _NON_ARTICLE_PATH_SEGMENTS,
    _STRONG_WEBSITE_NAV_TITLES,
    _host_matches_domain,
    _looks_like_section_path,
    _matches_known_title,
    _normalize_host,
    _normalize_title_key,
    _same_site,
    _word_count,
    get_website_content_reject_reason,
)
from app.utils.logger import get_logger
from app.utils.url import normalize_source_url_for_dedupe

logger = get_logger(__name__)


def normalize_external_id(external_id: str | None) -> str | None:
    """Normalize external_id to fit DB length constraints while staying stable."""
    if not external_id:
        return external_id
    if len(external_id) <= 255:
        return external_id
    digest = hashlib.sha1(external_id.encode("utf-8")).hexdigest()
    return f"hash:{digest}"

def normalize_extra_urls(extra_urls) -> List[str]:
    if not isinstance(extra_urls, list):
        return []
    seen = set()
    normalized: List[str] = []
    for raw in extra_urls:
        if not raw:
            continue
        candidate = str(raw).strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized

def get_source_urls(source) -> List[str]:
    """Get the full list of URLs to fetch for a given source."""
    metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
    extras = normalize_extra_urls(metadata.get("extra_urls"))
    urls = [source.url]
    for item in extras:
        if item != source.url:
            urls.append(item)
            
    # For website sources, avoid fetching multiple URLs that are mapped to the same RSS feed.
    source_type = source.type.value if hasattr(source.type, "value") else str(source.type).lower()
    if str(source_type) == "website":
        rss_map = metadata.get("rss_urls") if isinstance(metadata.get("rss_urls"), dict) else {}
        default_rss = rss_map.get(source.url) or metadata.get("rss_url")
        deduped_urls: List[str] = []
        seen_targets = set()
        for url in urls:
            target = rss_map.get(url) or default_rss or url
            target_key = str(target).strip()
            if not target_key or target_key in seen_targets:
                continue
            seen_targets.add(target_key)
            deduped_urls.append(url)
        if deduped_urls:
            urls = deduped_urls
    return urls

def _parse_iso_publish_time(value: str) -> datetime | None:
    """Parse an ISO-8601 publish time string, tolerating the ``Z`` UTC suffix.

    Returns ``None`` on any malformed input (the only exception ``fromisoformat``
    raises). We log at debug — feed data is noisy and a bad timestamp on one
    entry shouldn't taint the batch.
    """
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
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

            # fetch_publish_time_from_url already swallows network / decode
            # errors and returns None, so we don't need another layer here.
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

def dedupe_raw_contents(raw_contents: List[dict]) -> List[dict]:
    """Deduplicate merged contents from multiple URLs based on external_id, url or title."""
    seen = set()
    deduped = []
    for item in raw_contents:
        eid = normalize_external_id(item.get("external_id"))
        url = (item.get("url") or "").strip()
        url_key = normalize_source_url_for_dedupe(url) if url else ""
        key = eid or url_key or item.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
