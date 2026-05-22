"""Reader body loader: fetch/backfill/clean the body text served by the reader.

Extracted from the monolithic ``app.api.contents_reader`` module to keep the
HTTP layer thin. All functions are pure(-ish) helpers the API routes call to
materialise a readable body before we hand it to the translator.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.fetch.collectors.x_twitter_text import is_x_status_page_url
from app.domains.enrich.reader.shared import (
    _clean_x_reader_body,
    _derive_title_from_body,
    _extract_x_article_url,
    _looks_like_translation_refusal,
    _title_looks_like_url,
)
from app.config import get_settings
from app.models import Content, Source
from app.processors.extractor import ContentExtractor
from app.processors.translator import Translator
from app.domains.fetch.auth import try_parse_auth_credentials
from app.utils.cookies import normalize_cookie_dict
from app.utils.datetime import utcnow_naive
from app.utils.http import permissive_session_kwargs
from app.utils.logger import get_logger
from app.platform.security.ssrf import assert_public_http_target
from app.domains.ingest.quality_metadata import merge_content_quality_metadata
from app.utils.text import strip_html_tags, truncate_content, normalize_article_text

logger = get_logger(__name__)


_TRANSLATION_CACHE_KEYS = (
    "reader_translated_full_content",
    "reader_translated_body_hash",
    "reader_translation_ready",
    "reader_translation_ratio",
)


def clear_reader_translation_cache(metadata: dict) -> dict:
    """Drop any cached translation fields — callers use this whenever the body changes."""
    merged = dict(metadata)
    for key in _TRANSLATION_CACHE_KEYS:
        merged.pop(key, None)
    return merged


async def fetch_reader_fulltext(original_url: str) -> tuple[str, str]:
    """Best-effort public-URL fetch for reader fallback when DB has no body.

    Returns ``("", "")`` for any of: empty input, non-HTTP schemes, SSRF
    rejection, network / decode failure, tiny or low-signal HTML, or
    extraction that yields < 120 chars.
    """
    url = (original_url or "").strip()
    if not url:
        return "", ""
    if is_x_status_page_url(url):
        return "", ""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "", ""

    try:
        await assert_public_http_target(url)
    except ValueError:
        return "", ""

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    timeout = aiohttp.ClientTimeout(total=20, connect=8, sock_read=12)

    try:
        async with aiohttp.ClientSession(
            **permissive_session_kwargs(timeout=timeout, headers=headers)
        ) as session:
            async with session.get(url, allow_redirects=True) as response:
                if response.status != 200:
                    return "", ""
                html_text = await response.text(errors="ignore")
                final_url = str(response.url)
    except (aiohttp.ClientError, TimeoutError, UnicodeDecodeError) as exc:
        logger.debug("Reader fulltext fetch failed for %s: %s", url, exc)
        return "", ""

    if len(html_text) < 500:
        return "", ""

    extracted = await ContentExtractor().extract(html_text, final_url)
    clean_text = normalize_article_text(extracted or "").strip()
    if len(clean_text) < 120:
        return "", ""
    return clean_text, final_url


async def load_source_cookies_for_reader(db: AsyncSession, source_id: str) -> dict[str, str]:
    """Resolve cookies usable for paywalled/locked X long-article fetches.

    Preference order: source-local auth config → source metadata fallback →
    global settings. Silent on failure: the reader path tolerates an
    empty cookie dict by giving up on the hydration attempt.
    """
    cookies: dict[str, str] = {}
    if not source_id:
        return cookies

    try:
        result = await db.execute(
            select(Source).options(selectinload(Source.auth_config)).filter(Source.id == source_id)
        )
        source = result.scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001 - ORM may raise anything; degrade gracefully
        logger.debug("Reader cookie load failed for source %s: %s", source_id, exc)
        source = None

    if source:
        try:
            creds = try_parse_auth_credentials(source.auth_config)
            cookies = normalize_cookie_dict(creds.get("cookies"))
        except Exception as exc:  # noqa: BLE001 - credential decrypt can raise anything
            logger.debug("Reader cookie parse failed for source %s: %s", source_id, exc)
            cookies = {}
        if not cookies:
            meta = source.metadata_ if isinstance(source.metadata_, dict) else {}
            auth_token = str(meta.get("x_auth_token") or meta.get("auth_token") or "").strip()
            ct0 = str(meta.get("x_ct0_token") or meta.get("ct0") or "").strip()
            if auth_token and ct0:
                cookies = {"auth_token": auth_token, "ct0": ct0}

    if cookies:
        return cookies

    settings = get_settings()
    auth_token = str(getattr(settings, "x_auth_token", None) or "").strip()
    ct0 = str(getattr(settings, "x_ct0_token", None) or "").strip()
    if auth_token and ct0:
        return {"auth_token": auth_token, "ct0": ct0}
    return {}


async def fetch_x_article_fulltext(article_url: str, cookies: dict[str, str]) -> str:
    """Best-effort X long-article hydration used when the reader has only a stub tweet.

    Reaches into the X collector for its playwright-driven article hydrator.
    This crosses the ``enrich → fetch collectors`` boundary the Phase 4
    rule forbids; use a runtime ``importlib.import_module`` shim
    (explicitly allowed by ``scripts/check_domain_imports.py`` for
    runtime resolution) until Phase 4 / Phase 5 introduce a proper
    ``ArticleHydrator``-style port (see ``domains/contracts``).
    """
    if not article_url:
        return ""
    try:
        import importlib

        x_collector_module = importlib.import_module("app.collectors.x_twitter")
        collector = x_collector_module.XCollector()
        text_map = await collector._fetch_article_texts_with_playwright(
            [article_url], cookies=cookies or {}
        )
        text = (text_map.get(article_url) or "").strip()
        return text if len(text) >= 280 else ""
    except Exception as exc:  # noqa: BLE001 - playwright/network path can raise anything
        logger.debug("X article fulltext fetch failed for %s: %s", article_url, exc)
        return ""


async def upgrade_x_reader_body(
    content: Content,
    metadata: dict,
    body_raw: str,
    db: AsyncSession,
) -> tuple[Optional[str], Optional[dict]]:
    """Replace a stub X tweet body with the full long-article text when available."""
    article_url = _extract_x_article_url(metadata)
    source_cookies = await load_source_cookies_for_reader(db, str(content.source_id))
    article_text = await fetch_x_article_fulltext(article_url, source_cookies)
    if not article_text or len(article_text) <= len(body_raw):
        return None, None

    content.full_content = truncate_content(article_text, url=article_url or "")
    preview = article_text[:500]
    content.summary = preview + ("..." if len(article_text) > 500 else "")

    merged = clear_reader_translation_cache(metadata)
    if article_url:
        merged["article_url"] = article_url
    merged["article_fulltext"] = True
    merged["article_text_chars"] = len(article_text)
    merged = merge_content_quality_metadata(
        merged,
        title=content.title or "",
        full_content=content.full_content,
        summary=content.summary,
        translated_summary=content.translated_summary,
    )
    if _title_looks_like_url(content.title or ""):
        derived_title = _derive_title_from_body(article_text)
        if derived_title:
            content.title = derived_title[:500]
            if Translator().is_chinese(derived_title):
                content.translated_title = derived_title[:500]
    if content.translated_title and _looks_like_translation_refusal(content.translated_title):
        content.translated_title = None
    content.metadata_ = merged
    await db.commit()
    return article_text, merged


async def clean_x_body_if_needed(
    content: Content,
    metadata: dict,
    body_raw: str,
    db: AsyncSession,
) -> tuple[str, dict]:
    """Strip noise (quoted replies, footers) from an X tweet body in place."""
    cleaned_body = _clean_x_reader_body(body_raw)
    if not cleaned_body or cleaned_body == body_raw:
        return body_raw, metadata

    content.full_content = truncate_content(cleaned_body, url=content.original_url or "")
    preview = cleaned_body[:500]
    content.summary = preview + ("..." if len(cleaned_body) > 500 else "")

    merged = clear_reader_translation_cache(metadata)
    merged["x_reader_cleaned"] = True
    merged["x_reader_cleaned_at"] = utcnow_naive().isoformat()
    content.metadata_ = merged
    await db.commit()
    return cleaned_body, merged


def _website_body_needs_reader_backfill(content: Content, metadata: dict, body_raw: str) -> bool:
    """True when the stored body is an RSS/listing teaser, not article fulltext."""
    if (content.content_type or "").strip().lower() != "website":
        return False
    if not (content.original_url or "").strip():
        return False
    status = str(metadata.get("fulltext_status") or "").strip()
    body_len = len((content.full_content or "").strip())
    if status in {"summary_only", "title_only"}:
        return True
    # Partial rows can still be a single paywall chunk (e.g. NYT article-partial).
    if status == "partial" and body_len < 900:
        return True
    if not metadata.get("article_fulltext") and body_len < 280:
        return True
    return not body_raw


async def backfill_website_reader_body(
    content: Content,
    metadata: dict,
    body_raw: str,
    db: AsyncSession,
) -> tuple[str, dict]:
    """Fetch the original URL on demand when DB has no real article body."""
    if not _website_body_needs_reader_backfill(content, metadata, body_raw):
        return body_raw, metadata

    fetched_body, resolved_url = await fetch_reader_fulltext(content.original_url)
    if not fetched_body:
        return body_raw, metadata

    content.full_content = truncate_content(fetched_body, url=resolved_url or content.original_url or "")
    if not (content.summary or "").strip():
        preview = fetched_body[:500]
        content.summary = preview + ("..." if len(fetched_body) > 500 else "")

    merged = clear_reader_translation_cache(metadata)
    merged["reader_fulltext_backfilled_at"] = utcnow_naive().isoformat()
    merged["article_fulltext"] = True
    if resolved_url and resolved_url != content.original_url:
        merged["resolved_original_url"] = resolved_url
        content.original_url = resolved_url
    merged = merge_content_quality_metadata(
        merged,
        title=content.title or "",
        full_content=content.full_content,
        summary=content.summary,
        translated_summary=content.translated_summary,
    )
    content.metadata_ = merged
    await db.commit()
    return fetched_body, merged


async def ensure_reader_body(content: Content, db: AsyncSession) -> tuple[str, dict]:
    """Top-level entry: materialise a readable body, routing by content type.

    Priority:
    1. Upgrade stub X tweets (< 280 chars) via long-article fetch.
    2. Clean noise from existing X tweet bodies.
    3. Backfill website rows from the original URL when DB has no body.
    """
    def _finalize(body: str, meta: dict) -> tuple[str, dict]:
        return normalize_article_text(body), meta

    from app.domains.fetch.collectors.x_twitter_text import (
        looks_like_x_interstitial_text,
        is_x_status_page_url,
    )

    metadata = content.metadata_ if isinstance(content.metadata_, dict) else {}
    body_raw = (content.full_content or "").strip() or (content.summary or "").strip()
    source_type = (content.content_type or "").strip().lower()
    if source_type == "x" and body_raw and looks_like_x_interstitial_text(body_raw):
        title_fallback = (content.title or "").strip()
        # Never replace a longer body with a truncated listing title (often ~82 chars).
        if (
            title_fallback
            and not looks_like_x_interstitial_text(title_fallback)
            and len(title_fallback) > len(body_raw)
        ):
            body_raw = title_fallback
            content.full_content = truncate_content(title_fallback, url=content.original_url or "")
            preview = title_fallback[:500]
            content.summary = preview + ("..." if len(title_fallback) > 500 else "")
            metadata = clear_reader_translation_cache(metadata)
            metadata["x_interstitial_repaired_at"] = utcnow_naive().isoformat()
            content.metadata_ = metadata
            await db.commit()
    x_short_needs_upgrade = source_type == "x" and len(body_raw) < 280

    if x_short_needs_upgrade and source_type == "x":
        try:
            from app.domains.fetch.tweet_repair import repair_x_tweet_content

            source_row = await db.get(Source, content.source_id)
            if source_row and await repair_x_tweet_content(content, source_row):
                metadata = clear_reader_translation_cache(dict(content.metadata_ or {}))
                content.metadata_ = metadata
                await db.commit()
                body_raw = (content.full_content or "").strip() or (content.summary or "").strip()
                x_short_needs_upgrade = len(body_raw) < 280
        except Exception as exc:  # noqa: BLE001 - repair is best-effort
            logger.debug("X tweet repair skipped for %s: %s", getattr(content, "id", ""), exc)

    if x_short_needs_upgrade:
        upgraded_body, upgraded_metadata = await upgrade_x_reader_body(content, metadata, body_raw, db)
        if upgraded_body and upgraded_metadata is not None:
            return _finalize(upgraded_body, upgraded_metadata)

    if source_type == "x" and body_raw:
        body_raw, metadata = await clean_x_body_if_needed(content, metadata, body_raw, db)
        if _title_looks_like_url((content.title or "").strip()):
            derived_title = _derive_title_from_body(body_raw)
            if derived_title:
                content.title = derived_title[:500]
                if Translator().is_chinese(derived_title):
                    content.translated_title = derived_title[:500]
                if content.translated_title and _looks_like_translation_refusal(content.translated_title):
                    content.translated_title = None
                await db.commit()
        return _finalize(body_raw, metadata)

    body_raw, metadata = await backfill_website_reader_body(content, metadata, body_raw, db)
    return _finalize(body_raw, metadata)
