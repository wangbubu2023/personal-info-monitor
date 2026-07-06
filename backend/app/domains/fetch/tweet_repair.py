"""Re-fetch a single X tweet body when stored text is truncated or polluted."""

from __future__ import annotations

from typing import Any

import aiohttp

from app.domains.fetch.collectors.x_twitter_text import (
    build_title_from_text,
    extract_tweet_id,
    extract_username_from_url,
    normalize_tweet_url,
)
from app.models import Content, Source
from app.utils.http import permissive_session_kwargs
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _resolve_tweet_id(content: Content) -> str:
    tweet_id = str(content.external_id or "").strip()
    if not tweet_id:
        tweet_id = extract_tweet_id(content.original_url or "") or ""
    return tweet_id


def _resolve_username(content: Content, source: Source | None) -> str | None:
    if source is not None:
        username = extract_username_from_url(
            source.url,
            source.metadata_ if isinstance(source.metadata_, dict) else {},
        )
        if username:
            return username
    meta = content.metadata_ if isinstance(content.metadata_, dict) else {}
    return extract_username_from_url(content.original_url or "", meta)


async def fetch_x_tweet_public(username: str, tweet_id: str) -> dict[str, Any] | None:
    """Fetch one tweet via the public fxtwitter API (no X cookies required)."""
    handle = (username or "").strip().lstrip("@")
    tid = (tweet_id or "").strip()
    if not handle or not tid:
        return None

    api_url = f"https://api.fxtwitter.com/{handle}/status/{tid}"
    timeout = aiohttp.ClientTimeout(total=15, connect=5, sock_read=10)
    try:
        async with aiohttp.ClientSession(
            **permissive_session_kwargs(timeout=timeout)
        ) as session:
            async with session.get(api_url) as response:
                if response.status != 200:
                    return None
                payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        logger.debug("Public X tweet fetch failed for %s/%s: %s", handle, tid, exc)
        return None

    tweet = payload.get("tweet") if isinstance(payload, dict) else None
    if not isinstance(tweet, dict):
        return None

    text = (tweet.get("text") or "").strip()
    if len(text) < 20:
        return None

    canonical_url = str(tweet.get("url") or f"https://x.com/{handle}/status/{tid}")
    return {
        "external_id": tid,
        "title": build_title_from_text(text),
        "content": text,
        "url": canonical_url,
        "metadata": {"source_strategy": "fxtwitter_public"},
    }


async def refetch_x_tweet_from_source(
    content: Content,
    source: Source | None,
) -> dict[str, Any] | None:
    """Return collector-shaped dict for ``content`` via GraphQL or public API."""
    if (content.content_type or "").strip().lower() != "x":
        return None

    tweet_id = _resolve_tweet_id(content)
    if not tweet_id:
        return None

    username = _resolve_username(content, source)
    if not username:
        return None

    if source is not None:
        from importlib import import_module

        XCollector = import_module("app.domains.fetch.collectors.x_twitter").XCollector
        collector = XCollector()
        items = await collector._fetch_via_graphql(username, source)
        for item in items:
            eid = str(item.get("external_id") or "")
            url = normalize_tweet_url(str(item.get("url") or ""), logger=logger)
            if eid == tweet_id or tweet_id in url:
                return item

    return await fetch_x_tweet_public(username, tweet_id)


async def repair_x_tweet_content(content: Content, source: Source | None) -> bool:
    """Restore ``full_content`` / ``summary`` when the row is truncated or polluted."""
    item = await refetch_x_tweet_from_source(content, source)
    if not item:
        return False

    body = (item.get("content") or "").strip()
    existing_len = len((content.full_content or "").strip())
    if len(body) < 50 or len(body) <= existing_len:
        return False

    title = (item.get("title") or content.title or "").strip()
    content.full_content = body
    content.summary = body[:500] + ("..." if len(body) > 500 else "")
    if title:
        content.title = title

    from app.utils.datetime import utcnow_naive

    meta = dict(content.metadata_ if isinstance(content.metadata_, dict) else {})
    meta.pop("x_reader_cleaned", None)
    meta.pop("x_reader_cleaned_at", None)
    meta.pop("x_interstitial_repaired_at", None)
    meta["x_tweet_repaired_at"] = utcnow_naive().isoformat()
    meta["x_tweet_repair_strategy"] = (
        (item.get("metadata") or {}).get("source_strategy") or "graphql"
    )
    content.metadata_ = meta
    logger.info("Repaired X tweet body for %s (%d chars)", content.id, len(body))
    return True


__all__ = [
    "fetch_x_tweet_public",
    "refetch_x_tweet_from_source",
    "repair_x_tweet_content",
]
