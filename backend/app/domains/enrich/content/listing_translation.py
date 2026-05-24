"""Translate title + summary for feed/listing surfaces (资讯中心, digest, search).

Runs as a non-blocking sidecar after ingest finish, and can be scheduled when
the daily digest is loaded so older rows gradually gain ``translated_*`` fields.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from app.domains.enrich.reader.shared import (
    _is_valid_title_translation,
    _is_valid_translation_text,
    _title_looks_like_url,
)
from app.domains.ingest.summary_clean import clean_listing_summary
from app.processors.translator import Translator
from app.utils.logger import get_logger
from app.utils.text import strip_html_tags

logger = get_logger(__name__)

_TITLE_TIMEOUT_SECONDS = 12.0
_SUMMARY_TIMEOUT_SECONDS = 20.0

_scheduled_ids: set[str] = set()


def listing_translation_enabled() -> bool:
    """Whether automatic listing translation should run."""
    from app.config import get_settings
    from app.platform.config.system_settings import get_system_settings_sync

    settings = get_settings()
    if not settings.ai_processing_enabled or not settings.enrich_translate_enabled:
        return False

    sys_settings = get_system_settings_sync() or {}
    if not sys_settings.get("translation_enabled", True):
        return False
    if not sys_settings.get("title_translation_enabled", True):
        return False
    return True


def content_needs_listing_translation(
    *,
    title: str,
    summary: Optional[str],
    translated_title: Optional[str],
    translated_summary: Optional[str],
    translator: Optional[Translator] = None,
) -> bool:
    """Return True when title or summary still needs a Chinese listing translation."""
    if not listing_translation_enabled():
        return False

    active = translator or Translator()
    original_title = (title or "").strip()
    if (
        original_title
        and not _title_looks_like_url(original_title)
        and not active.is_chinese(original_title)
        and not _is_valid_title_translation(original_title, translated_title)
    ):
        return True

    original_summary = strip_html_tags(summary or "").strip()
    if (
        original_summary
        and len(original_summary) >= 5
        and not active.is_chinese(original_summary)
        and not _is_valid_translation_text(translated_summary)
    ):
        return True

    return False


def schedule_listing_translation_backfill(content_ids: list[str], *, max_items: int = 30) -> None:
    """Fire-and-forget translation for rows missing ``translated_*`` (deduped)."""
    if not listing_translation_enabled():
        return

    for raw_id in content_ids[:max_items]:
        cid = str(raw_id or "").strip()
        if not cid or cid in _scheduled_ids:
            continue
        _scheduled_ids.add(cid)
        try:
            asyncio.create_task(_run_scheduled_translation(cid))
        except RuntimeError:
            _scheduled_ids.discard(cid)


async def _run_scheduled_translation(content_id: str) -> None:
    try:
        await translate_listing_fields_async(content_id)
    finally:
        _scheduled_ids.discard(content_id)


async def translate_listing_fields_async(content_id: str) -> bool:
    """Populate ``translated_title`` / ``translated_summary`` for one Content row."""
    if not listing_translation_enabled():
        return False

    from app.background import get_llm_semaphore

    sem = get_llm_semaphore()
    async with sem:
        return await _translate_listing_fields_impl(content_id)


async def _translate_listing_fields_impl(content_id: str) -> bool:
    from app.database import SessionLocal
    from app.domains.ingest.quality_metadata import merge_content_quality_metadata
    from app.models import Content

    db = SessionLocal()
    changed = False
    try:
        content = db.query(Content).filter(Content.id == content_id).first()
        if content is None:
            return False

        translator = Translator()
        target_language = _resolve_target_language()

        original_title = (content.title or "").strip()
        if (
            original_title
            and not _title_looks_like_url(original_title)
            and not translator.is_chinese(original_title)
            and not _is_valid_title_translation(original_title, content.translated_title)
        ):
            candidate = await _translate_with_timeout(
                translator,
                original_title,
                target_language,
                timeout_seconds=_TITLE_TIMEOUT_SECONDS,
            )
            if _is_valid_title_translation(original_title, candidate):
                content.translated_title = str(candidate).strip()[:500]
                changed = True

        original_summary = clean_listing_summary(strip_html_tags(content.summary or "").strip())
        if (
            original_summary
            and len(original_summary) >= 5
            and not translator.is_chinese(original_summary)
            and not _is_valid_translation_text(content.translated_summary)
        ):
            candidate = await _translate_with_timeout(
                translator,
                original_summary,
                target_language,
                timeout_seconds=_SUMMARY_TIMEOUT_SECONDS,
            )
            if _is_valid_translation_text(candidate):
                content.translated_summary = clean_listing_summary(str(candidate).strip()[:4000]) or None
                changed = True

        if not changed:
            return False

        content.metadata_ = merge_content_quality_metadata(
            content.metadata_ or {},
            title=content.title or "",
            full_content=content.full_content,
            summary=content.summary,
            translated_summary=content.translated_summary,
        )
        db.commit()
        logger.info(
            "Listing translation saved for %s (title=%s summary=%s)",
            content_id,
            bool(content.translated_title),
            bool(content.translated_summary),
        )
        return True
    except Exception as exc:  # noqa: BLE001 - sidecar must not break ingest/digest
        logger.debug("Listing translation failed for %s: %s", content_id, exc)
        db.rollback()
        return False
    finally:
        db.close()


def _resolve_target_language() -> str:
    try:
        from app.platform.config.system_settings import get_system_settings_sync

        lang = str((get_system_settings_sync() or {}).get("auto_translate_language") or "zh-CN").strip()
        return lang or "zh-CN"
    except Exception:  # noqa: BLE001 - settings fallback must not block listing translation
        return "zh-CN"


async def _translate_with_timeout(
    translator: Translator,
    text: str,
    target_language: str,
    *,
    timeout_seconds: float,
) -> Optional[str]:
    try:
        return await asyncio.wait_for(
            translator.translate(text, target_language),
            timeout=timeout_seconds,
        )
    except (TimeoutError, asyncio.TimeoutError):
        return None
    except Exception as exc:  # noqa: BLE001
        logger.debug("Listing translate call failed: %s", exc)
        return None


__all__ = [
    "content_needs_listing_translation",
    "listing_translation_enabled",
    "schedule_listing_translation_backfill",
    "translate_listing_fields_async",
]
