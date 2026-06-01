"""HTTP layer for the reader endpoints.

Responsibilities kept to: route binding, request parsing, and stitching
together the domain helpers in :mod:`app.domains.enrich.reader`. All
body fetching / translation / streaming logic lives under that package
(moved out of ``app.services.reader`` in Phase 4 step 5 of the
module-refactor blueprint; the old path is kept as a re-export shim).

Legacy private symbols (``_fetch_reader_fulltext`` etc.) are re-exported
at module scope so downstream callers (``app.api.contents``, test files
that ``patch("app.api.contents_reader.XXX")``) keep working unchanged.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.interfaces.http.content_shared import (
    _build_clean_reader_html,
    _is_valid_translation_text,
    _reader_body_hash,
    _split_for_reader,
)
from app.database import get_async_db
from app.models import Content
from app.domains.enrich.reader import body_loader as _body_loader
from app.domains.enrich.reader import streaming as _streaming
from app.domains.enrich.reader import translation as _translation

router = APIRouter()


# ---------------------------------------------------------------------------
# Legacy private-name re-exports.
#
# Many existing tests use ``patch("app.api.contents_reader._foo", ...)`` to
# stub internals, and ``app.api.contents`` re-imports a handful of these
# names. Keep the surface intact so the refactor is a pure internal move.
# ---------------------------------------------------------------------------

_clear_reader_translation_cache = _body_loader.clear_reader_translation_cache
_fetch_reader_fulltext = _body_loader.fetch_reader_fulltext
_load_source_cookies_for_reader = _body_loader.load_source_cookies_for_reader
_fetch_x_article_fulltext = _body_loader.fetch_x_article_fulltext
_upgrade_x_reader_body = _body_loader.upgrade_x_reader_body
_clean_x_body_if_needed = _body_loader.clean_x_body_if_needed
_backfill_website_reader_body = _body_loader.backfill_website_reader_body
_ensure_reader_body = _body_loader.ensure_reader_body

_ensure_translated_title = _translation.ensure_translated_title
_translate_reader_text = _translation.translate_reader_text
_translate_reader_paragraph = _translation.translate_reader_paragraph
_persist_reader_translation_cache = _translation.persist_reader_translation_cache

_json_line = _streaming.json_line
_emit_cached_reader_translation = _streaming.emit_cached_reader_translation
_build_reader_translation_done_payload = _streaming.build_reader_translation_done_payload
_emit_reader_translation = _streaming.emit_reader_translation


# Re-expose the third-party module names that tests patch (e.g.
# ``patch("app.api.contents_reader.aiohttp.ClientSession", ...)``).
# Keeping these imports at module scope preserves patch targets even
# though the routes themselves no longer reference them directly.
from app.processors.extractor import ContentExtractor  # noqa: E402,F401 - patch target
from app.processors.translator import Translator  # noqa: E402,F401 - patch target
from app.tasks.fetch_auth_helpers import try_parse_auth_credentials  # noqa: E402,F401 - patch target
from app.utils.cookies import normalize_cookie_dict  # noqa: E402,F401 - patch target
from app.platform.security.ssrf import assert_public_http_target  # noqa: E402,F401 - patch target
from app.utils.text import strip_html_tags, truncate_content  # noqa: E402,F401 - patch target
from app.config import get_settings  # noqa: E402,F401 - patch target
import aiohttp  # noqa: E402,F401 - patch target


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
        "source_id": str(content.source_id),
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
    request: Request,
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
            disconnect_check=request.is_disconnected,
        ),
        media_type="application/x-ndjson; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
