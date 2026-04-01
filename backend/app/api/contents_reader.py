"""Reader and translation routes for content items."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
import json
import time
from typing import Optional
from urllib.parse import urlparse
from uuid import UUID

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.content_shared import (
    _build_clean_reader_html,
    _clean_x_reader_body,
    _derive_title_from_body,
    _extract_x_article_url,
    _is_valid_title_translation,
    _is_valid_translation_text,
    _looks_like_translation_refusal,
    _reader_body_hash,
    _split_for_reader,
    _title_looks_like_url,
)
from app.config import get_settings
from app.database import get_async_db
from app.models import Content, Source
from app.processors.extractor import ContentExtractor
from app.processors.translator import Translator
from app.tasks.fetch_auth_helpers import try_parse_auth_credentials
from app.utils.cookies import normalize_cookie_dict
from app.utils.datetime import utcnow_naive
from app.utils.text import strip_html_tags, truncate_content

router = APIRouter()


def _clear_reader_translation_cache(metadata: dict) -> dict:
    merged = dict(metadata)
    merged.pop("reader_translated_full_content", None)
    merged.pop("reader_translated_body_hash", None)
    merged.pop("reader_translation_ready", None)
    merged.pop("reader_translation_ratio", None)
    return merged


async def _fetch_reader_fulltext(original_url: str) -> tuple[str, str]:
    """Best-effort full-text fetch for reader fallback when DB has no body."""
    url = (original_url or "").strip()
    if not url:
        return "", ""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
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
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, allow_redirects=True) as response:
                if response.status != 200:
                    return "", ""
                html_text = await response.text(errors="ignore")
                final_url = str(response.url)
    except Exception:
        return "", ""

    if len(html_text) < 500:
        return "", ""

    extracted = await ContentExtractor().extract(html_text, final_url)
    clean_text = strip_html_tags(extracted or "").strip()
    if len(clean_text) < 120:
        return "", ""
    return clean_text, final_url


async def _load_source_cookies_for_reader(db: AsyncSession, source_id: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    if not source_id:
        return cookies

    try:
        result = await db.execute(
            select(Source).options(selectinload(Source.auth_config)).filter(Source.id == source_id)
        )
        source = result.scalar_one_or_none()
    except Exception:
        source = None

    if source:
        try:
            creds = try_parse_auth_credentials(source.auth_config)
            cookies = normalize_cookie_dict(creds.get("cookies"))
        except Exception:
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


async def _fetch_x_article_fulltext(article_url: str, cookies: dict[str, str]) -> str:
    """Best-effort X long-article hydration (no auth in reader path)."""
    if not article_url:
        return ""
    try:
        from app.collectors.x_twitter import XCollector

        collector = XCollector()
        text_map = await collector._fetch_article_texts_with_playwright([article_url], cookies=cookies or {})
        text = (text_map.get(article_url) or "").strip()
        return text if len(text) >= 280 else ""
    except Exception:
        return ""


async def _ensure_translated_title(
    content: Content,
    db: AsyncSession,
    *,
    timeout_seconds: float = 8.0,
) -> str:
    """Ensure translated_title exists (on-demand), then return display title."""
    original = (content.title or "").strip()
    translated = (content.translated_title or "").strip()
    if translated or not original or _title_looks_like_url(original):
        return translated or original

    translator = Translator()
    if translator.is_chinese(original):
        return original

    async def _translate_once() -> Optional[str]:
        try:
            return await translator.translate(original, "zh-CN")
        except Exception:
            return None

    try:
        candidate = await asyncio.wait_for(_translate_once(), timeout=timeout_seconds)
    except Exception:
        candidate = None

    if not _is_valid_translation_text(candidate):
        try:
            candidate = await asyncio.wait_for(
                translator.translate_with_fallback(original, "zh-CN"),
                timeout=timeout_seconds,
            )
        except Exception:
            candidate = None

    if _is_valid_title_translation(original, candidate):
        content.translated_title = str(candidate).strip()[:500]
        await db.commit()
        return content.translated_title
    return original


async def _upgrade_x_reader_body(
    content: Content,
    metadata: dict,
    body_raw: str,
    db: AsyncSession,
) -> tuple[Optional[str], Optional[dict]]:
    article_url = _extract_x_article_url(metadata)
    source_cookies = await _load_source_cookies_for_reader(db, str(content.source_id))
    article_text = await _fetch_x_article_fulltext(article_url, source_cookies)
    if not article_text or len(article_text) <= len(body_raw):
        return None, None

    content.full_content = truncate_content(article_text, url=article_url or "")
    preview = article_text[:500]
    content.summary = preview + ("..." if len(article_text) > 500 else "")

    merged = _clear_reader_translation_cache(metadata)
    if article_url:
        merged["article_url"] = article_url
    merged["article_fulltext"] = True
    merged["article_text_chars"] = len(article_text)
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


async def _clean_x_body_if_needed(
    content: Content,
    metadata: dict,
    body_raw: str,
    db: AsyncSession,
) -> tuple[str, dict]:
    cleaned_body = _clean_x_reader_body(body_raw)
    if not cleaned_body or cleaned_body == body_raw:
        return body_raw, metadata

    content.full_content = truncate_content(cleaned_body, url=content.original_url or "")
    preview = cleaned_body[:500]
    content.summary = preview + ("..." if len(cleaned_body) > 500 else "")

    merged = _clear_reader_translation_cache(metadata)
    merged["x_reader_cleaned"] = True
    merged["x_reader_cleaned_at"] = utcnow_naive().isoformat()
    content.metadata_ = merged
    await db.commit()
    return cleaned_body, merged


async def _backfill_website_reader_body(
    content: Content,
    metadata: dict,
    body_raw: str,
    db: AsyncSession,
) -> tuple[str, dict]:
    if body_raw or content.content_type != "website" or not content.original_url:
        return body_raw, metadata

    fetched_body, resolved_url = await _fetch_reader_fulltext(content.original_url)
    if not fetched_body:
        return body_raw, metadata

    content.full_content = truncate_content(fetched_body, url=resolved_url or content.original_url or "")
    if not (content.summary or "").strip():
        preview = fetched_body[:500]
        content.summary = preview + ("..." if len(fetched_body) > 500 else "")

    merged = _clear_reader_translation_cache(metadata)
    merged["reader_fulltext_backfilled_at"] = utcnow_naive().isoformat()
    if resolved_url and resolved_url != content.original_url:
        merged["resolved_original_url"] = resolved_url
        content.original_url = resolved_url
    content.metadata_ = merged
    await db.commit()
    return fetched_body, merged


async def _ensure_reader_body(content: Content, db: AsyncSession) -> tuple[str, dict]:
    """Ensure body text exists for reader; backfill from original URL on demand."""
    metadata = content.metadata_ if isinstance(content.metadata_, dict) else {}
    body_raw = (content.full_content or "").strip() or (content.summary or "").strip()
    source_type = (content.content_type or "").strip().lower()
    x_short_needs_upgrade = source_type == "x" and len(body_raw) < 280

    if x_short_needs_upgrade:
        upgraded_body, upgraded_metadata = await _upgrade_x_reader_body(content, metadata, body_raw, db)
        if upgraded_body and upgraded_metadata is not None:
            return upgraded_body, upgraded_metadata

    if source_type == "x" and body_raw:
        body_raw, metadata = await _clean_x_body_if_needed(content, metadata, body_raw, db)
        if _title_looks_like_url((content.title or "").strip()):
            derived_title = _derive_title_from_body(body_raw)
            if derived_title:
                content.title = derived_title[:500]
                if Translator().is_chinese(derived_title):
                    content.translated_title = derived_title[:500]
                if content.translated_title and _looks_like_translation_refusal(content.translated_title):
                    content.translated_title = None
                await db.commit()
        return body_raw, metadata

    return await _backfill_website_reader_body(content, metadata, body_raw, db)


async def _translate_reader_text(
    text: str,
    *,
    per_chunk_timeout_seconds: float = 8.0,
    total_timeout_seconds: float = 22.0,
) -> str:
    """Translate long body text to Chinese in small chunks."""
    if not text:
        return ""
    translator = Translator()
    if translator.is_chinese(text):
        return text

    chunks: list[str] = []
    current = ""
    for paragraph in _split_for_reader(text):
        segment = paragraph + "\n\n"
        if len(current) + len(segment) > 2400 and current:
            chunks.append(current)
            current = segment
        else:
            current += segment
    if current:
        chunks.append(current)

    translated_parts: list[str] = []
    started_at = time.monotonic()
    for index, chunk in enumerate(chunks):
        elapsed = time.monotonic() - started_at
        if elapsed >= total_timeout_seconds:
            translated_parts.extend(chunks[index:])
            break

        remaining_budget = total_timeout_seconds - elapsed
        timeout = min(per_chunk_timeout_seconds, max(0.1, remaining_budget))
        try:
            translated = await asyncio.wait_for(translator.translate(chunk, "zh-CN"), timeout=timeout)
        except Exception:
            translated = None
        if not _is_valid_translation_text(translated):
            try:
                translated = await asyncio.wait_for(
                    translator.translate_with_fallback(chunk, "zh-CN"),
                    timeout=min(timeout, 6.0),
                )
            except Exception:
                translated = translated or None
        translated_parts.append(translated or chunk)
    return "\n\n".join(translated_parts).strip()


def _json_line(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


async def _translate_reader_paragraph(
    paragraph: str,
    translator: Translator,
    *,
    timeout_seconds: float,
) -> tuple[str, bool]:
    try:
        translated = await asyncio.wait_for(
            translator.translate(paragraph, "zh-CN"),
            timeout=timeout_seconds,
        )
    except Exception:
        translated = None
    if not _is_valid_translation_text(translated):
        try:
            translated = await asyncio.wait_for(
                translator.translate_with_fallback(paragraph, "zh-CN"),
                timeout=min(timeout_seconds, 6.0),
            )
        except Exception:
            translated = translated or None
    piece = (translated or paragraph).strip()
    return piece, _is_valid_translation_text(translated)


async def _persist_reader_translation_cache(
    *,
    content: Content,
    db: AsyncSession,
    metadata: dict,
    body_hash: str,
    final_text: str,
    ratio: float,
) -> bool:
    merged = dict(metadata)
    merged["reader_translated_full_content"] = final_text[:200000]
    merged["reader_translated_body_hash"] = body_hash
    merged["reader_translation_ready"] = True
    merged["reader_translation_ratio"] = round(ratio, 3)
    content.metadata_ = merged
    try:
        await db.commit()
        return True
    except Exception:
        await db.rollback()
        return False


async def _emit_cached_reader_translation(cached_text: str) -> AsyncGenerator[bytes, None]:
    cached_paragraphs = _split_for_reader(cached_text) or [cached_text]
    for index, paragraph in enumerate(cached_paragraphs):
        yield _json_line({"type": "chunk", "index": index, "text": paragraph, "translated": True})
    yield _json_line(
        {
            "type": "done",
            "paragraphs_total": len(cached_paragraphs),
            "paragraphs_streamed": len(cached_paragraphs),
            "translated": True,
            "translation_cached": True,
            "message": "ok",
        }
    )


def _build_reader_translation_done_payload(
    *,
    total_count: int,
    translated_parts: list[str],
    translated_count: int,
    translated_success: bool,
    cache_written: bool,
    ratio: float,
) -> dict:
    message = "ok"
    if not translated_success:
        message = "译文生成未达到可读阈值（<60%），请重试或切换翻译模型" if translated_count > 0 else "未检测到可用翻译结果，已回退原文"
    elif translated_count < total_count:
        message = "部分段落翻译失败，已回退原文"

    return {
        "type": "done",
        "paragraphs_total": total_count,
        "paragraphs_streamed": len(translated_parts),
        "translated": translated_success,
        "translation_cached": cache_written,
        "translated_count": translated_count,
        "partial_fallback": translated_success and translated_count < total_count,
        "ratio": round(ratio, 3),
        "message": message,
    }


async def _emit_reader_translation(
    *,
    content: Content,
    db: AsyncSession,
    metadata: dict,
    body_hash: str,
    cached,
    cached_body_hash: str,
    cached_ready: bool,
    paragraphs: list[str],
    title: str,
    source_name: str,
) -> AsyncGenerator[bytes, None]:
    yield _json_line(
        {
            "type": "init",
            "id": str(content.id),
            "title": title,
            "source_name": source_name,
            "original_url": content.original_url,
            "publish_time": content.publish_time.isoformat() if content.publish_time else None,
            "paragraphs_total": len(paragraphs),
        }
    )

    if not paragraphs:
        yield _json_line(
            {
                "type": "done",
                "paragraphs_total": 0,
                "paragraphs_streamed": 0,
                "translated": False,
                "translation_cached": False,
                "message": "暂无可阅读正文",
            }
        )
        return

    if body_hash and cached_body_hash == body_hash and (cached_ready or _is_valid_translation_text(cached)):
        async for item in _emit_cached_reader_translation(str(cached).strip()):
            yield item
        return

    translator = Translator()
    translated_parts: list[str] = []
    translated_count = 0
    per_chunk_timeout_seconds = 12.0

    for index, paragraph in enumerate(paragraphs):
        piece, is_translated_piece = await _translate_reader_paragraph(
            paragraph,
            translator,
            timeout_seconds=per_chunk_timeout_seconds,
        )
        translated_parts.append(piece)
        translated_count += 1 if is_translated_piece else 0
        yield _json_line(
            {
                "type": "chunk",
                "index": index,
                "text": piece,
                "translated": is_translated_piece,
            }
        )

    final_text = "\n\n".join(p for p in translated_parts if p).strip()
    total_count = len(paragraphs)
    ratio = (translated_count / total_count) if total_count else 0.0
    translated_success = bool(total_count and ratio >= 0.6)
    cache_written = (
        await _persist_reader_translation_cache(
            content=content,
            db=db,
            metadata=metadata,
            body_hash=body_hash,
            final_text=final_text,
            ratio=ratio,
        )
        if translated_success
        else False
    )
    yield _json_line(
        _build_reader_translation_done_payload(
            total_count=total_count,
            translated_parts=translated_parts,
            translated_count=translated_count,
            translated_success=translated_success,
            cache_written=cache_written,
            ratio=ratio,
        )
    )


@router.get("/{content_id}/reader")
async def get_reader_payload(
    content_id: UUID,
    translate: bool = Query(False, description="Translate body on demand when true"),
    db: AsyncSession = Depends(get_async_db),
):
    """Get reader payload. Translation is on-demand via query param."""
    result = await db.execute(
        select(Content)
        .options(selectinload(Content.source))
        .filter(Content.id == content_id)
    )
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    body_raw, metadata = await _ensure_reader_body(content, db)
    body_hash = _reader_body_hash(body_raw)
    cached = metadata.get("reader_translated_full_content")
    cached_body_hash = str(metadata.get("reader_translated_body_hash") or "")
    cached_ready = bool(metadata.get("reader_translation_ready"))
    has_translated_cache = bool(
        body_hash and cached_body_hash == body_hash and (cached_ready or _is_valid_translation_text(cached))
    )
    body_zh = cached.strip() if has_translated_cache else ""
    body_translation_source = "cache_full_content" if has_translated_cache else "none"

    if translate:
        await _ensure_translated_title(content, db)
        if not body_zh and body_raw:
            translated_text = await _translate_reader_text(body_raw)
            if _is_valid_translation_text(translated_text):
                body_zh = translated_text
                body_translation_source = "live_full_content"
            if body_zh:
                merged = dict(metadata)
                merged["reader_translated_full_content"] = body_zh[:200000]
                merged["reader_translated_body_hash"] = body_hash
                merged["reader_translation_ready"] = True
                merged["reader_translation_ratio"] = 1.0
                content.metadata_ = merged
                await db.commit()

    display_title = (content.translated_title or content.title or "").strip() if translate else (content.title or "").strip()
    display_body = body_zh if (translate and body_zh) else body_raw
    clean_html = _build_clean_reader_html(
        title=display_title,
        source_name=content.source.name if content.source else "",
        original_url=content.original_url,
        publish_time=content.publish_time,
        body_zh=display_body,
    )

    return {
        "id": str(content.id),
        "source_name": content.source.name if content.source else "",
        "title": content.title,
        "translated_title": content.translated_title,
        "original_url": content.original_url,
        "publish_time": content.publish_time.isoformat() if content.publish_time else None,
        "body_raw": body_raw,
        "body_zh": display_body,
        "translation_requested": translate,
        "translation_cached": has_translated_cache,
        "has_translation_cache": has_translated_cache,
        "body_translation_source": body_translation_source,
        "body_translation_is_summary": False,
        "clean_html": clean_html,
    }


@router.get("/{content_id}/reader/translate-stream")
async def stream_reader_translation(
    content_id: UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """Stream translated reader body paragraph-by-paragraph (NDJSON)."""
    result = await db.execute(
        select(Content)
        .options(selectinload(Content.source))
        .filter(Content.id == content_id)
    )
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    body_raw, metadata = await _ensure_reader_body(content, db)
    title = await _ensure_translated_title(content, db)
    body_hash = _reader_body_hash(body_raw)
    cached = metadata.get("reader_translated_full_content")
    cached_body_hash = str(metadata.get("reader_translated_body_hash") or "")
    cached_ready = bool(metadata.get("reader_translation_ready"))
    paragraphs = _split_for_reader(body_raw) or ([body_raw.strip()] if body_raw else [])
    source_name = content.source.name if content.source else ""

    return StreamingResponse(
        _emit_reader_translation(
            content=content,
            db=db,
            metadata=metadata,
            body_hash=body_hash,
            cached=cached,
            cached_body_hash=cached_body_hash,
            cached_ready=cached_ready,
            paragraphs=paragraphs,
            title=title,
            source_name=source_name,
        ),
        media_type="application/x-ndjson; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
