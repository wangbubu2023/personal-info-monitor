"""Translation helpers for the reader module.

Kept separate from ``body_loader`` so tests can patch translation
independently from fetch/backfill logic.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.enrich.reader.shared import (
    _is_valid_title_translation,
    _is_valid_translation_text,
    _split_for_reader,
    _title_looks_like_url,
)
from app.models import Content
from app.processors.translator import Translator
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def ensure_translated_title(
    content: Content,
    db: AsyncSession,
    *,
    timeout_seconds: float = 8.0,
) -> str:
    """Translate the title on-demand when we don't have a Chinese one yet.

    Short-circuits for URLs-as-titles and already-Chinese titles. Uses
    the primary translator first and falls back to a cheaper provider
    when validation rejects the first result. Never raises: callers
    get the best-available title (original on total failure).
    """
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
        except Exception as exc:  # noqa: BLE001 - translator may raise anything
            logger.debug("Title translation primary path failed: %s", exc)
            return None

    candidate: Optional[str]
    try:
        candidate = await asyncio.wait_for(_translate_once(), timeout=timeout_seconds)
    except (TimeoutError, asyncio.TimeoutError):
        candidate = None

    if not _is_valid_translation_text(candidate):
        try:
            candidate = await asyncio.wait_for(
                translator.translate_with_fallback(original, "zh-CN"),
                timeout=timeout_seconds,
            )
        except (TimeoutError, asyncio.TimeoutError):
            candidate = None
        except Exception as exc:  # noqa: BLE001 - translator fallback may raise anything
            logger.debug("Title translation fallback raised: %s", exc)
            candidate = None

    if _is_valid_title_translation(original, candidate):
        content.translated_title = str(candidate).strip()[:500]
        await db.commit()
        return content.translated_title
    return original


async def translate_reader_paragraph(
    paragraph: str,
    translator: Translator,
    *,
    timeout_seconds: float,
) -> tuple[str, bool]:
    """Translate a single paragraph; return ``(piece, is_valid_translation)``."""
    translated: Optional[str]
    try:
        translated = await asyncio.wait_for(
            translator.translate(paragraph, "zh-CN"),
            timeout=timeout_seconds,
        )
    except (TimeoutError, asyncio.TimeoutError):
        translated = None
    except Exception as exc:  # noqa: BLE001 - translator may raise anything
        logger.debug("Paragraph translation primary raised: %s", exc)
        translated = None
    if not _is_valid_translation_text(translated):
        try:
            translated = await asyncio.wait_for(
                translator.translate_with_fallback(paragraph, "zh-CN"),
                timeout=min(timeout_seconds, 6.0),
            )
        except (TimeoutError, asyncio.TimeoutError):
            translated = translated or None
        except Exception as exc:  # noqa: BLE001 - translator fallback may raise anything
            logger.debug("Paragraph translation fallback raised: %s", exc)
            translated = translated or None
    piece = (translated or paragraph).strip()
    return piece, _is_valid_translation_text(translated)


async def translate_reader_text(
    text: str,
    *,
    per_chunk_timeout_seconds: float = 8.0,
    total_timeout_seconds: float = 22.0,
) -> str:
    """Translate a long body by splitting into ~2.4k-char chunks.

    Fails soft: if a chunk times out it's emitted as-is. Stops early
    once the accumulated budget ``total_timeout_seconds`` is exhausted.
    """
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
        translated: Optional[str]
        try:
            translated = await asyncio.wait_for(translator.translate(chunk, "zh-CN"), timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError):
            translated = None
        except Exception as exc:  # noqa: BLE001 - translator may raise anything
            logger.debug("Reader chunk translation primary raised: %s", exc)
            translated = None
        if not _is_valid_translation_text(translated):
            try:
                translated = await asyncio.wait_for(
                    translator.translate_with_fallback(chunk, "zh-CN"),
                    timeout=min(timeout, 6.0),
                )
            except (TimeoutError, asyncio.TimeoutError):
                translated = translated or None
            except Exception as exc:  # noqa: BLE001 - translator fallback may raise anything
                logger.debug("Reader chunk translation fallback raised: %s", exc)
                translated = translated or None
        translated_parts.append(translated or chunk)
    return "\n\n".join(translated_parts).strip()


async def persist_reader_translation_cache(
    *,
    content: Content,
    db: AsyncSession,
    metadata: dict,
    body_hash: str,
    final_text: str,
    ratio: float,
) -> bool:
    """Write translation cache keys; rollback and report False on commit failure."""
    merged = dict(metadata)
    merged["reader_translated_full_content"] = final_text[:200000]
    merged["reader_translated_body_hash"] = body_hash
    merged["reader_translation_ready"] = True
    merged["reader_translation_ratio"] = round(ratio, 3)
    content.metadata_ = merged
    try:
        await db.commit()
        return True
    except Exception as exc:  # noqa: BLE001 - ORM may raise anything; rollback and degrade
        logger.debug("Reader translation cache commit failed: %s", exc)
        await db.rollback()
        return False
