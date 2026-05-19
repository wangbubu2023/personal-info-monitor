"""Helpers for keyword normalization, dedupe, and bilingual equivalents."""

from __future__ import annotations

import asyncio
import json
import re
import unicodedata

import httpx

from app.utils.logger import get_logger
from app.utils.ttl_cache import TTLCache

logger = get_logger(__name__)

_translation_cache = TTLCache(ttl_seconds=3600)
_translation_punctuation = " \t\r\n\"'`“”‘’.,;:!?()[]{}<>《》【】"
_PUBLIC_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
_STATIC_EQUIVALENTS: dict[str, list[str]] = {
    "gpt": ["生成式预训练变换器"],
    "生成式预训练变换器": ["GPT"],
    "gemini": ["谷歌双子座", "双子座"],
    "谷歌双子座": ["Gemini"],
    "双子座": ["Gemini"],
}


def normalize_keyword_value(value: str) -> str:
    """Normalize user keyword input for comparison and dedupe."""
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def keyword_identity_key(value: str) -> str:
    """Case-insensitive dedupe key for keyword identity."""
    return normalize_keyword_value(value).casefold()


def dedupe_keywords_case_insensitive(values: list[str]) -> tuple[list[str], list[str]]:
    """Return unique keywords preserving order, plus skipped duplicates."""
    seen: set[str] = set()
    unique_values: list[str] = []
    skipped_values: list[str] = []

    for raw_value in values:
        value = normalize_keyword_value(raw_value)
        if not value:
            continue
        identity = keyword_identity_key(value)
        if identity in seen:
            skipped_values.append(value)
            continue
        seen.add(identity)
        unique_values.append(value)

    return unique_values, skipped_values


def _sanitize_equivalent_terms(original: str, translated: str) -> list[str]:
    """Extract concise equivalent search terms from translation output."""
    raw_text = normalize_keyword_value(translated).strip(_translation_punctuation)
    if not raw_text:
        return []

    candidates = re.split(r"[\n,，;/；、|()（）\[\]【】]+", raw_text)
    candidates.append(raw_text)

    original_key = keyword_identity_key(original)
    seen: set[str] = {original_key}
    sanitized: list[str] = []

    for candidate in candidates:
        value = normalize_keyword_value(candidate).strip(_translation_punctuation)
        if not value:
            continue
        identity = keyword_identity_key(value)
        if identity in seen:
            continue
        seen.add(identity)
        sanitized.append(value)

    return sanitized


def _static_equivalent_terms(keyword: str) -> list[str]:
    """Return curated aliases for high-frequency product names and acronyms."""
    return list(_STATIC_EQUIVALENTS.get(keyword_identity_key(keyword), []))


async def _translate_keyword_via_public_endpoint(keyword: str, target_language: str) -> str | None:
    """Use a lightweight public translate endpoint as a no-config fallback."""
    params = {
        "client": "gtx",
        "sl": "auto",
        "tl": target_language,
        "dt": "t",
        "q": keyword,
    }

    try:
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
            response = await client.get(_PUBLIC_TRANSLATE_URL, params=params)
            response.raise_for_status()
    except Exception as exc:
        logger.warning("Keyword public translation failed for %s: %s", keyword, exc)
        return None

    try:
        payload = response.json()
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, list) or not payload:
        return None

    segments = payload[0]
    if not isinstance(segments, list):
        return None

    translated_parts: list[str] = []
    for segment in segments:
        if not isinstance(segment, list) or not segment:
            continue
        text = segment[0]
        if isinstance(text, str) and text.strip():
            translated_parts.append(text.strip())

    translated = "".join(translated_parts).strip()
    return translated or None


async def build_equivalent_terms(keyword: str, *, match_type: str = "contains") -> list[str]:
    """Best-effort bilingual expansion for exact/contains keywords."""
    value = normalize_keyword_value(keyword)
    if not value or match_type == "regex":
        return []

    from app.processors.translator import Translator

    translator = Translator()
    target_language = "en" if translator.is_chinese(value) else "zh-CN"
    cache_key = f"{keyword_identity_key(value)}::{target_language}"
    cached = _translation_cache.get(cache_key)
    if cached is not None:
        return list(cached)

    translated: str | None = None
    if len(value) >= 5:
        try:
            translated = await asyncio.wait_for(
                translator.translate(value, target_language),
                timeout=2.5,
            )
        except Exception as exc:
            logger.warning("Keyword equivalent generation failed for %s: %s", value, exc)

    if not translated:
        translated = await _translate_keyword_via_public_endpoint(value, target_language)

    equivalents = _sanitize_equivalent_terms(value, translated or "")
    for alias in _static_equivalent_terms(value):
        equivalents.extend(_sanitize_equivalent_terms(value, alias))
    equivalents, _ = dedupe_keywords_case_insensitive(equivalents)
    _translation_cache.set(cache_key, equivalents)
    return equivalents


_MAX_MANUAL_EQUIVALENT_TERMS = 48


def normalize_manual_equivalent_terms(raw: list[str], *, main_keyword: str) -> list[str]:
    """Dedupe, drop empty, cap length.

    Only drops a manual line when it is the **exact same string** as the main keyword
    (after :func:`normalize_keyword_value`), not when it merely differs by case.

    Case-only variants (e.g. main ``openclaw``, manual ``OpenClaw``) are **kept**: they are
    useful when ``case_sensitive`` is true, and are harmless for matching when false (matcher
    lowercases for contains/exact).
    """
    main_norm = normalize_keyword_value(main_keyword)
    seen: set[str] = set()
    out: list[str] = []
    for item in raw or []:
        value = normalize_keyword_value(str(item))
        if not value or len(value) > 255:
            continue
        if value == main_norm:
            continue
        ident = keyword_identity_key(value)
        if ident in seen:
            continue
        seen.add(ident)
        out.append(value)
        if len(out) >= _MAX_MANUAL_EQUIVALENT_TERMS:
            break
    return out


def merge_equivalent_term_lists(manual: list[str], auto: list[str]) -> list[str]:
    """Union by case-insensitive identity; manual order first, then auto-only terms."""
    seen: set[str] = set()
    merged: list[str] = []
    for term in manual + auto:
        ident = keyword_identity_key(term)
        if ident in seen:
            continue
        seen.add(ident)
        merged.append(normalize_keyword_value(term))
    return merged


async def compute_stored_equivalent_terms(
    keyword: str,
    *,
    match_type: str,
    manual_terms: list[str],
    include_auto: bool,
) -> list[str]:
    """
    Persisted equivalent_terms = manual ∪ (optional auto translation).

    When include_auto is False, only manual_terms are used (avoids bad machine translations).
    Regex keywords do not use auto expansion.
    """
    value = normalize_keyword_value(keyword)
    manual = normalize_manual_equivalent_terms(manual_terms, main_keyword=value)
    if match_type == "regex" or not include_auto:
        return manual

    auto = await build_equivalent_terms(value, match_type=match_type)
    return merge_equivalent_term_lists(manual, auto)
