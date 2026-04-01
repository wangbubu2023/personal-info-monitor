"""System settings persistence and runtime access helpers."""

import copy
import threading
import time
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.models.system_setting import SystemSetting
from app.utils.logger import get_logger

logger = get_logger(__name__)

SYSTEM_SETTINGS_KEY = "global"
_CACHE_TTL_SECONDS = 30
_cache_lock = threading.Lock()
_cache_value: Dict[str, Any] | None = None
_cache_deadline = 0.0

DEFAULT_SYSTEM_SETTINGS: Dict[str, Any] = {
    "ai_model": {
        "provider": "ollama",
        "model": "deepseek-r1:14b",
        "api_base": "http://localhost:11434",
        "temperature": 0.7,
        "max_tokens": 1000,
    },
    "translation_model": {
        "provider": "ollama",
        "model": "translategemma:12b",
        "api_base": "http://localhost:11434",
    },
    "translation_enabled": True,
    "title_translation_enabled": True,
    "auto_translate_language": "zh-CN",
    "summarization_enabled": True,
    "translation_cloud_fallback_enabled": False,
    "summarization_cloud_fallback_enabled": False,
    "email_notifications_enabled": False,
    "limits": {
        "max_sources": 200,
        "max_digest_candidates": 12,
        "max_hourly_digest_input_items": 200,
    },
}

_SETTINGS_BOOL_KEYS = (
    "translation_enabled",
    "title_translation_enabled",
    "summarization_enabled",
    "translation_cloud_fallback_enabled",
    "summarization_cloud_fallback_enabled",
    "email_notifications_enabled",
)
_AI_MODEL_KEYS = ("provider", "model", "api_base", "temperature", "max_tokens", "api_key")
_TRANS_MODEL_KEYS = ("provider", "model", "api_base", "api_key")
_LIMIT_RULES = {
    "max_sources": (200, 1, 5000),
    "max_digest_candidates": (12, 3, 30),
    "max_hourly_digest_input_items": (200, 20, 2000),
}


def _coerce_int(value: Any, default: int, *, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(min_value, min(max_value, parsed))


def _merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _cache_set(settings: Dict[str, Any]) -> None:
    global _cache_value, _cache_deadline
    with _cache_lock:
        _cache_value = copy.deepcopy(settings)
        _cache_deadline = time.time() + _CACHE_TTL_SECONDS


def _cache_get() -> Dict[str, Any] | None:
    with _cache_lock:
        if _cache_value is None:
            return None
        if time.time() > _cache_deadline:
            return None
        return copy.deepcopy(_cache_value)


def _cache_invalidate() -> None:
    global _cache_value, _cache_deadline
    with _cache_lock:
        _cache_value = None
        _cache_deadline = 0.0


def _coerce_persisted_settings(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    return {}


def _apply_patch(current: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    updated = copy.deepcopy(current)

    ai_model = patch.get("ai_model")
    if isinstance(ai_model, dict):
        target = updated.setdefault("ai_model", {})
        for key in _AI_MODEL_KEYS:
            if key in ai_model:
                target[key] = ai_model[key]

    translation_model = patch.get("translation_model")
    if isinstance(translation_model, dict):
        target = updated.setdefault("translation_model", {})
        for key in _TRANS_MODEL_KEYS:
            if key in translation_model:
                target[key] = translation_model[key]

    if "auto_translate_language" in patch:
        updated["auto_translate_language"] = patch["auto_translate_language"]

    for key in _SETTINGS_BOOL_KEYS:
        if key in patch:
            updated[key] = patch[key]

    limits_patch = patch.get("limits")
    if isinstance(limits_patch, dict):
        target_limits = updated.setdefault("limits", {})
        for key, (default, min_value, max_value) in _LIMIT_RULES.items():
            if key in limits_patch:
                target_limits[key] = _coerce_int(
                    limits_patch[key],
                    default,
                    min_value=min_value,
                    max_value=max_value,
                )

    return updated


def _mask_sensitive(settings: Dict[str, Any]) -> Dict[str, Any]:
    response = copy.deepcopy(settings)
    for field in ("ai_model", "translation_model"):
        model = response.get(field) or {}
        if isinstance(model, dict):
            model["has_api_key"] = bool(model.get("api_key"))
            model.pop("api_key", None)
            response[field] = model
    return response


def get_system_settings_for_response(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Public helper for API response payload."""
    return _mask_sensitive(settings)


def get_system_settings_sync(force_refresh: bool = False) -> Dict[str, Any]:
    """Get merged settings for sync runtime code paths."""
    if not force_refresh:
        cached = _cache_get()
        if cached is not None:
            return cached

    payload: Dict[str, Any] = {}
    db = SessionLocal()
    try:
        row = db.query(SystemSetting).filter(SystemSetting.key == SYSTEM_SETTINGS_KEY).first()
        payload = _coerce_persisted_settings(row.value if row else {})
    except Exception as e:
        logger.warning(f"Load system settings (sync) failed, using defaults: {e}")
    finally:
        db.close()

    merged = _merge_dict(DEFAULT_SYSTEM_SETTINGS, payload)
    _cache_set(merged)
    return copy.deepcopy(merged)


async def get_system_settings_async(db: AsyncSession, force_refresh: bool = False) -> Dict[str, Any]:
    """Get merged settings for async API code paths."""
    if not force_refresh:
        cached = _cache_get()
        if cached is not None:
            return cached

    payload: Dict[str, Any] = {}
    try:
        result = await db.execute(select(SystemSetting).filter(SystemSetting.key == SYSTEM_SETTINGS_KEY))
        row = result.scalar_one_or_none()
        payload = _coerce_persisted_settings(row.value if row else {})
    except Exception as e:
        logger.warning(f"Load system settings (async) failed, using defaults: {e}")

    merged = _merge_dict(DEFAULT_SYSTEM_SETTINGS, payload)
    _cache_set(merged)
    return copy.deepcopy(merged)


async def update_system_settings_async(db: AsyncSession, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Apply patch and persist merged settings."""
    current = await get_system_settings_async(db, force_refresh=True)
    merged = _apply_patch(current, patch or {})

    result = await db.execute(select(SystemSetting).filter(SystemSetting.key == SYSTEM_SETTINGS_KEY))
    row = result.scalar_one_or_none()
    if row is None:
        row = SystemSetting(key=SYSTEM_SETTINGS_KEY, value=merged)
        db.add(row)
    else:
        row.value = merged

    await db.commit()
    _cache_set(merged)
    return copy.deepcopy(merged)


def invalidate_system_settings_cache() -> None:
    """Invalidate in-memory cache (useful for tests)."""
    _cache_invalidate()
