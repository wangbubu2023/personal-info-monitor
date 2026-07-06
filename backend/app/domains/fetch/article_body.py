"""Public-URL article body fetch — second-hop fetch (and reader fallback)."""

from __future__ import annotations

from importlib import import_module
from urllib.parse import urlparse

import aiohttp

from app.domains.fetch.acceptance import is_x_long_article
from app.domains.fetch.collectors.x_twitter_text import (
    build_title_from_text,
    extract_article_urls,
    is_x_status_page_url,
    looks_like_x_interstitial_text,
    title_looks_like_url,
)
from app.models import Content, Source
from app.utils.structured_article import extract_structured_article
from app.platform.security.ssrf import check_before_fetch, fetch_public_http_text
from app.utils.http import permissive_session_kwargs
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger
from app.utils.text import normalize_article_text, truncate_content
from app.domains.fetch.collectors.bpc_strategies import get_spoofed_headers

logger = get_logger(__name__)

_MIN_ARTICLE_BODY_CHARS = 280
ContentExtractor = None


async def _extract_article_text(html_text: str, final_url: str) -> str:
    structured = extract_structured_article(html_text, min_chars=120)
    if structured:
        return structured.text
    extractor_cls = ContentExtractor
    if extractor_cls is None:
        extractor_cls = import_module("app.domains.ingest.extractor").ContentExtractor
    return await extractor_cls().extract(html_text, final_url)


async def fetch_public_article_body(original_url: str, metadata: dict | None = None) -> tuple[str, str]:
    """Best-effort public-URL fetch + extraction for ingest finalize / reader.

    Returns ``("", "")`` on failure or when extracted text is shorter than 120 chars.
    """
    url = (original_url or "").strip()
    if not url:
        return "", ""
    if is_x_status_page_url(url):
        return "", ""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "", ""

    ua_default = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    bpc_headers = get_spoofed_headers(metadata or {}, ua_default)

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        **bpc_headers,
    }
    timeout = aiohttp.ClientTimeout(total=20, connect=8, sock_read=12)

    try:
        async with aiohttp.ClientSession(
            **permissive_session_kwargs(timeout=timeout, headers=headers)
        ) as session:
            response = await fetch_public_http_text(session, url, text_errors="ignore")
            if response.status != 200:
                return "", ""
            html_text = response.text
            final_url = response.url
    except (aiohttp.ClientError, TimeoutError, UnicodeDecodeError, ValueError) as exc:
        logger.debug("Public article fetch failed for %s: %s", url, exc)
        return "", ""

    if len(html_text) < 500:
        return "", ""

    extracted = await _extract_article_text(html_text, final_url)
    clean_text = normalize_article_text(extracted or "").strip()
    if len(clean_text) < 120:
        return "", ""
    return clean_text, final_url


async def fetch_cookie_article_body(
    original_url: str,
    cookies: dict[str, str],
    *,
    source_url: str = "",
) -> str:
    """Best-effort first-party article fetch with source auth cookies."""
    url = (original_url or "").strip()
    if not url or not cookies or is_x_status_page_url(url):
        return ""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ""
    if (parsed.hostname or "").lower() == "news.google.com" and "/rss/articles/" in (parsed.path or ""):
        return ""

    try:
        await check_before_fetch(url, source_url=source_url, cookies=cookies)
    except ValueError as exc:
        logger.debug("Cookie article fetch blocked for %s: %s", url, exc)
        return ""

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    try:
        cookie_jar = aiohttp.CookieJar()
        url_obj = aiohttp.client_reqrep.URL(url)
        for key, value in cookies.items():
            if not key or value is None:
                continue
            cookie_jar.update_cookies({str(key): str(value)}, response_url=url_obj)

        async with aiohttp.ClientSession(
            **permissive_session_kwargs(cookie_jar=cookie_jar)
        ) as session:
            response = await fetch_public_http_text(
                session,
                url,
                source_url=source_url,
                validation_cookies=cookies,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            )
            if response.status != 200:
                return ""
            html_text = response.text

        extracted = await _extract_article_text(html_text, url)
        clean_text = normalize_article_text(extracted or "").strip()
        if looks_like_x_interstitial_text(clean_text):
            return ""
        return clean_text if len(clean_text) >= 120 else ""
    except (aiohttp.ClientError, TimeoutError, UnicodeDecodeError, ValueError, OSError) as exc:
        logger.debug("Cookie article fetch failed for %s: %s", url, exc)
        return ""


def website_body_needs_public_fetch(content: Content, metadata: dict) -> bool:
    """True when ingest finalize should try to pull the article page."""
    if (content.content_type or "").strip().lower() not in {"website", "rss"}:
        return False
    if not (content.original_url or "").strip():
        return False
    body_len = len((content.full_content or "").strip())
    if metadata.get("article_fulltext") and body_len >= _MIN_ARTICLE_BODY_CHARS:
        return False
    if body_len >= 1200:
        return False
    status = str(metadata.get("fulltext_status") or "").strip()
    if status in {"summary_only", "title_only"}:
        return True
    if status == "partial" and body_len < 900:
        return True
    return body_len < _MIN_ARTICLE_BODY_CHARS


async def ensure_article_body_during_finish(content: Content) -> bool:
    """Fetch and persist article body during fetch finalization.

    Returns True when ``full_content`` was upgraded from the public URL.
    """
    metadata = content.metadata_ if isinstance(content.metadata_, dict) else {}
    body_raw = (content.full_content or "").strip() or (content.summary or "").strip()
    if not website_body_needs_public_fetch(content, metadata) and len(body_raw) >= _MIN_ARTICLE_BODY_CHARS:
        return False

    fetched_body, resolved_url = await fetch_public_article_body(content.original_url or "", metadata)
    if not fetched_body:
        return False

    content.full_content = truncate_content(
        fetched_body,
        url=resolved_url or content.original_url or "",
    )
    if not (content.summary or "").strip():
        preview = fetched_body[:500]
        content.summary = preview + ("..." if len(fetched_body) > 500 else "")

    merged = dict(metadata)
    merged["article_fulltext"] = True
    merged["ingest_body_fetched_at"] = merged.get("ingest_body_fetched_at") or utcnow_naive().isoformat()
    if resolved_url and resolved_url != content.original_url:
        merged["resolved_original_url"] = resolved_url
        content.original_url = resolved_url
    content.metadata_ = merged
    logger.info(
        "Fetch finalize fetched article body for %s (%d chars)",
        content.id,
        len(fetched_body),
    )
    return True


def _load_source_cookies(source: Source | None) -> dict[str, str]:
    if source is None or not source.auth_config_id:
        return {}
    from app.domains.fetch.auth import try_parse_auth_credentials
    from app.utils.cookies import normalize_cookie_dict

    creds = try_parse_auth_credentials(source.auth_config)
    return normalize_cookie_dict(creds.get("cookies"))


def resolve_x_article_url(content: Content, metadata: dict) -> str:
    for candidate in (
        str(metadata.get("article_url") or ""),
        str(content.original_url or ""),
        str(content.title or ""),
        str(content.full_content or ""),
        str(content.summary or ""),
    ):
        urls = extract_article_urls(candidate)
        if urls:
            return urls[0]
    return ""


async def fetch_x_article_fulltext(article_url: str, cookies: dict[str, str]) -> str:
    """Best-effort X long-article hydration during fetch finalization."""
    if not article_url:
        return ""
    try:
        import importlib

        x_collector_module = importlib.import_module("app.domains.fetch.collectors.x_twitter")
        collector = x_collector_module.XCollector()
        text_map = await collector._fetch_article_texts_with_playwright(
            [article_url], cookies=cookies or {}
        )
        text = (text_map.get(article_url) or "").strip()
        return text if len(text) >= _MIN_ARTICLE_BODY_CHARS else ""
    except Exception as exc:  # noqa: BLE001 - playwright/network path can raise anything
        logger.debug("X article fulltext fetch failed for %s: %s", article_url, exc)
        return ""


def x_long_article_needs_hydration(content: Content, metadata: dict) -> bool:
    if not is_x_long_article(content, metadata):
        return False
    body_len = len((content.full_content or "").strip())
    if metadata.get("article_fulltext") and body_len >= _MIN_ARTICLE_BODY_CHARS:
        return False
    return body_len < _MIN_ARTICLE_BODY_CHARS


async def ensure_x_article_body_during_finish(content: Content, source: Source | None) -> bool:
    """Hydrate X long-article body during fetch finalization when only a stub exists."""
    metadata = content.metadata_ if isinstance(content.metadata_, dict) else {}
    if not x_long_article_needs_hydration(content, metadata):
        return False

    article_url = resolve_x_article_url(content, metadata)
    if not article_url:
        return False

    article_text = await fetch_x_article_fulltext(article_url, _load_source_cookies(source))
    if not article_text:
        return False

    content.full_content = truncate_content(article_text, url=article_url)
    if not (content.summary or "").strip():
        preview = article_text[:500]
        content.summary = preview + ("..." if len(article_text) > 500 else "")

    merged = dict(metadata)
    merged["article_url"] = article_url
    merged["article_fulltext"] = True
    merged["article_text_chars"] = len(article_text)
    merged["ingest_body_fetched_at"] = merged.get("ingest_body_fetched_at") or utcnow_naive().isoformat()
    if title_looks_like_url(content.title or ""):
        derived_title = build_title_from_text(article_text)
        if derived_title:
            content.title = derived_title[:500]
    if article_url != content.original_url:
        merged.setdefault("tweet_url", content.original_url)
        content.original_url = article_url
    content.metadata_ = merged
    logger.info(
        "Fetch finalize hydrated X article body for %s (%d chars)",
        content.id,
        len(article_text),
    )
    return True


async def ensure_content_bodies_during_finish(content: Content, source: Source | None) -> None:
    """Run all fetch-time body hydration before acceptance / downstream stages."""
    content_type = (content.content_type or "").strip().lower()
    if content_type in {"website", "rss"}:
        await ensure_article_body_during_finish(content)
    elif content_type == "x":
        await ensure_x_article_body_during_finish(content, source)
