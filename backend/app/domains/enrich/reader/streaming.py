"""NDJSON streaming support for the reader translation endpoint.

Splits body paragraphs, emits ``init`` / ``chunk`` / ``done`` frames,
and renders a cached translation when available.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.enrich.reader.shared import _is_valid_translation_text, _split_for_reader
from app.models import Content
from app.platform.llm.policy import resolve_translation_state
from app.platform.llm.translator import Translator
from app.domains.enrich.reader.translation import (
    persist_reader_translation_cache,
    translate_reader_paragraph,
)
from app.platform.llm.translator import get_translation_settings


def json_line(payload: dict) -> bytes:
    """Serialise one NDJSON record with a trailing newline."""
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


async def emit_cached_reader_translation(cached_text: str) -> AsyncGenerator[bytes, None]:
    """Replay a cached translation as-if it were being generated live."""
    cached_paragraphs = _split_for_reader(cached_text) or [cached_text]
    for index, paragraph in enumerate(cached_paragraphs):
        yield json_line({"type": "chunk", "index": index, "text": paragraph, "translated": True})
    yield json_line(
        {
            "type": "done",
            "paragraphs_total": len(cached_paragraphs),
            "paragraphs_streamed": len(cached_paragraphs),
            "translated": True,
            "translation_cached": True,
            "message": "ok",
        }
    )


def build_reader_translation_done_payload(
    *,
    total_count: int,
    translated_parts: list[str],
    translated_count: int,
    translated_success: bool,
    cache_written: bool,
    ratio: float,
) -> dict:
    """Build the terminal ``done`` frame summarising translation outcome."""
    message = "ok"
    if not translated_success:
        message = (
            "译文生成未达到可读阈值（<60%），请重试或切换翻译模型"
            if translated_count > 0
            else "未检测到可用翻译结果，已回退原文"
        )
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


async def emit_reader_translation(
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
    disconnect_check: Optional[Callable[[], Awaitable[bool]]] = None,
) -> AsyncGenerator[bytes, None]:
    """Paragraph-by-paragraph NDJSON stream for the reader translate endpoint.

    Decision flow:

    1. Emit the ``init`` frame with counts and metadata.
    2. If we have a valid cached translation with a matching body hash,
       replay it via :func:`emit_cached_reader_translation`.
    3. Otherwise translate live, paragraph-by-paragraph. Paragraphs
       shorter than 5 chars skip translation (``Translator.translate``
       does the same — counting them would depress the success ratio).
    4. Write the translation cache when success ratio ≥ 0.45.
    5. Emit a summarising ``done`` frame.
    """
    yield json_line(
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
        yield json_line(
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

    state = await resolve_translation_state(automatic=False)
    if not state.effective:
        yield json_line(
            {
                "type": "done",
                "paragraphs_total": len(paragraphs),
                "paragraphs_streamed": 0,
                "translated": False,
                "translation_cached": False,
                "message": f"翻译功能当前不可用：{state.reason}",
            }
        )
        return

    if body_hash and cached_body_hash == body_hash and (cached_ready or _is_valid_translation_text(cached)):
        async for item in emit_cached_reader_translation(str(cached).strip()):
            yield item
        return

    provider = str(get_translation_settings().get("provider") or "ollama").strip().lower()
    translator = Translator()
    translated_parts: list[str] = []
    translated_count = 0
    per_chunk_timeout_seconds = 60.0 if provider == "ollama" else 22.0
    # Skip paragraphs < 5 chars: Translator.translate no-ops on those, so
    # counting them in the denominator would artificially depress the
    # success ratio and trip the "translation failed" message below.
    eligible_total = sum(1 for p in paragraphs if len(p.strip()) >= 5)

    for index, paragraph in enumerate(paragraphs):
        if disconnect_check is not None:
            try:
                if await disconnect_check():
                    yield json_line(
                        {
                            "type": "done",
                            "paragraphs_total": len(paragraphs),
                            "paragraphs_streamed": index,
                            "translated": False,
                            "translation_cached": False,
                            "message": "client disconnected",
                        }
                    )
                    return
            except Exception:  # noqa: BLE001 — disconnect probe is best-effort
                pass

        if len(paragraph.strip()) < 5:
            piece = paragraph.strip()
            translated_parts.append(piece)
            yield json_line(
                {
                    "type": "chunk",
                    "index": index,
                    "text": piece,
                    "translated": False,
                }
            )
            continue
        piece, is_translated_piece = await translate_reader_paragraph(
            paragraph,
            translator,
            timeout_seconds=per_chunk_timeout_seconds,
        )
        translated_parts.append(piece)
        translated_count += 1 if is_translated_piece else 0
        yield json_line(
            {
                "type": "chunk",
                "index": index,
                "text": piece,
                "translated": is_translated_piece,
            }
        )

    final_text = "\n\n".join(p for p in translated_parts if p).strip()
    total_count = len(paragraphs)
    if eligible_total <= 0:
        ratio = 0.0
        translated_success = False
    else:
        ratio = translated_count / eligible_total
        # 0.45 threshold (below the audit-era 0.6) trades strict quality for
        # fewer "everything failed" toasts on short articles where 1-2 chunks
        # hit timeouts but the rest look fine.
        translated_success = ratio >= 0.45
    cache_written = (
        await persist_reader_translation_cache(
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
    yield json_line(
        build_reader_translation_done_payload(
            total_count=total_count,
            translated_parts=translated_parts,
            translated_count=translated_count,
            translated_success=translated_success,
            cache_written=cache_written,
            ratio=ratio,
        )
    )
