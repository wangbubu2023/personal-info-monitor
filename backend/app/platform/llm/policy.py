"""Unified AI feature policy resolver.

This module is the single control plane for deciding whether an AI capability
may run. Model configuration answers "what can be called"; product settings
answer "what the user currently allows to run automatically".
"""

from __future__ import annotations

import copy
import json
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Callable

from app.ai.provider import ModelRuntime, get_runtime_from_system_settings
from app.platform.config.settings import get_settings
from app.platform.config.system_settings import get_system_settings_sync
from app.platform.observability.logger import get_logger

logger = get_logger(__name__)

_RUNTIME_CACHE_TTL_SECONDS = 20.0
_runtime_cache_lock = threading.Lock()
_runtime_cache: dict[str, tuple[float, bool]] = {}


@dataclass(frozen=True)
class AiFeatureState:
    """Resolved state for one AI capability."""

    enabled: bool
    runtime_ready: bool
    effective: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AiPolicyStatus:
    """Status payload exposed to the settings UI."""

    global_ai: AiFeatureState
    writing: AiFeatureState
    auto_summary: AiFeatureState
    auto_listing_translation: AiFeatureState
    reader_translation: AiFeatureState
    subjective_scoring: AiFeatureState
    hard_disabled: bool
    paused: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "global_ai": self.global_ai.to_dict(),
            "writing": self.writing.to_dict(),
            "auto_summary": self.auto_summary.to_dict(),
            "auto_listing_translation": self.auto_listing_translation.to_dict(),
            "reader_translation": self.reader_translation.to_dict(),
            "subjective_scoring": self.subjective_scoring.to_dict(),
            "hard_disabled": self.hard_disabled,
            "paused": self.paused,
        }


def invalidate_ai_policy_cache() -> None:
    """Clear short-lived runtime availability cache."""

    with _runtime_cache_lock:
        _runtime_cache.clear()


def _bool_setting(settings: dict[str, Any], key: str, default: bool) -> bool:
    value = settings.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value) and value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled"}:
            return False
    return default


def ai_hard_disabled() -> bool:
    """Deployment-level hard kill switch for new outbound AI calls."""

    return bool(getattr(get_settings(), "pim_ai_hard_disable", False))


def ai_processing_paused(settings: dict[str, Any] | None = None) -> bool:
    """User-level global pause stored in system_settings."""

    runtime_settings = settings if isinstance(settings, dict) else (get_system_settings_sync() or {})
    return _bool_setting(runtime_settings, "ai_processing_paused", False)


def _model_snapshot(settings: dict[str, Any], setting_keys: tuple[str, ...]) -> str:
    compact: dict[str, Any] = {}
    for setting_key in setting_keys:
        block = settings.get(setting_key) if isinstance(settings.get(setting_key), dict) else {}
        compact[setting_key] = {
            "provider": block.get("provider"),
            "model": block.get("model"),
            "api_base": block.get("api_base"),
            "has_api_key": bool(block.get("api_key")),
        }
    return json.dumps(compact, sort_keys=True, ensure_ascii=True)


def _model_configured(settings: dict[str, Any], setting_key: str) -> bool:
    block = settings.get(setting_key) if isinstance(settings.get(setting_key), dict) else {}
    provider = str(block.get("provider") or "").strip().lower()
    model = str(block.get("model") or "").strip()
    if not provider:
        return False
    if setting_key == "score_model" and not model:
        return False
    return bool(model)


def _runtime_cache_get(cache_key: str) -> bool | None:
    with _runtime_cache_lock:
        row = _runtime_cache.get(cache_key)
        if not row:
            return None
        deadline, ready = row
        if time.time() > deadline:
            _runtime_cache.pop(cache_key, None)
            return None
        return ready


def _runtime_cache_set(cache_key: str, ready: bool) -> None:
    with _runtime_cache_lock:
        _runtime_cache[cache_key] = (time.time() + _RUNTIME_CACHE_TTL_SECONDS, ready)


async def _runtime_ready(
    settings: dict[str, Any],
    cache_namespace: str,
    setting_keys: tuple[str, ...],
    resolver: Callable[[], Awaitable[ModelRuntime | None]],
) -> bool:
    cache_key = f"{cache_namespace}:{_model_snapshot(settings, setting_keys)}"
    cached = _runtime_cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        ready = await resolver() is not None
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.debug("AI runtime check failed for %s: %s", cache_namespace, exc)
        ready = False
    _runtime_cache_set(cache_key, ready)
    return ready


def _blocked_state(*, enabled: bool, runtime_ready: bool = False, reason: str) -> AiFeatureState:
    return AiFeatureState(enabled=enabled, runtime_ready=runtime_ready, effective=False, reason=reason)


def _global_block(settings: dict[str, Any]) -> str | None:
    if ai_hard_disabled():
        return "hard_disabled"
    if ai_processing_paused(settings):
        return "paused"
    return None


async def _resolve_model_feature_state(
    *,
    settings: dict[str, Any],
    enabled: bool,
    setting_keys: tuple[str, ...],
    cache_namespace: str,
    resolver: Callable[[], Awaitable[ModelRuntime | None]],
) -> AiFeatureState:
    blocked = _global_block(settings)
    if blocked:
        return _blocked_state(enabled=enabled, reason=blocked)
    if not enabled:
        return _blocked_state(enabled=False, reason="disabled")

    ready = await _runtime_ready(settings, cache_namespace, setting_keys, resolver)
    if ready:
        return AiFeatureState(enabled=True, runtime_ready=True, effective=True, reason="ready")
    if not any(_model_configured(settings, setting_key) for setting_key in setting_keys):
        return _blocked_state(enabled=True, runtime_ready=False, reason="waiting_model_config")
    return _blocked_state(enabled=True, runtime_ready=False, reason="model_unavailable")


async def _resolve_primary_or_fallback_runtime(
    *,
    primary_key: str,
    fallback_key: str,
    fallback_enabled: bool,
    default_temperature: float,
    default_max_tokens: int,
) -> ModelRuntime | None:
    primary = await get_runtime_from_system_settings(
        setting_key=primary_key,
        default_provider="ollama",
        default_model="",
        default_api_base="http://localhost:11434",
        default_temperature=default_temperature,
        default_max_tokens=default_max_tokens,
    )
    if primary is not None or not fallback_enabled:
        return primary
    return await get_runtime_from_system_settings(
        setting_key=fallback_key,
        default_provider="openai",
        default_model="",
        default_api_base=None,
        default_temperature=default_temperature,
        default_max_tokens=default_max_tokens,
    )


def resolve_global_ai_state(settings: dict[str, Any] | None = None) -> AiFeatureState:
    runtime_settings = settings if isinstance(settings, dict) else (get_system_settings_sync() or {})
    if ai_hard_disabled():
        return _blocked_state(enabled=True, runtime_ready=True, reason="hard_disabled")
    if ai_processing_paused(runtime_settings):
        return _blocked_state(enabled=True, runtime_ready=True, reason="paused")
    return AiFeatureState(enabled=True, runtime_ready=True, effective=True, reason="ready")


async def resolve_writing_state(settings: dict[str, Any] | None = None) -> AiFeatureState:
    runtime_settings = copy.deepcopy(settings if isinstance(settings, dict) else (get_system_settings_sync() or {}))
    return await _resolve_model_feature_state(
        settings=runtime_settings,
        enabled=True,
        setting_keys=("ai_model",),
        cache_namespace="writing",
        resolver=lambda: get_runtime_from_system_settings(
            setting_key="ai_model",
            default_provider="ollama",
            default_model="",
            default_api_base="http://localhost:11434",
            default_temperature=0.2,
            default_max_tokens=2400,
        ),
    )


async def resolve_auto_summary_state(settings: dict[str, Any] | None = None) -> AiFeatureState:
    runtime_settings = copy.deepcopy(settings if isinstance(settings, dict) else (get_system_settings_sync() or {}))
    enabled = _bool_setting(runtime_settings, "auto_summary_enabled", True)
    fallback_enabled = _bool_setting(runtime_settings, "summarization_fallback_enabled", False)
    setting_keys = ("ai_model", "summarization_fallback") if fallback_enabled else ("ai_model",)
    return await _resolve_model_feature_state(
        settings=runtime_settings,
        enabled=enabled,
        setting_keys=setting_keys,
        cache_namespace="auto_summary",
        resolver=lambda: _resolve_primary_or_fallback_runtime(
            primary_key="ai_model",
            fallback_key="summarization_fallback",
            fallback_enabled=fallback_enabled,
            default_temperature=0.2,
            default_max_tokens=1000,
        ),
    )


async def resolve_translation_state(
    *,
    automatic: bool,
    settings: dict[str, Any] | None = None,
) -> AiFeatureState:
    runtime_settings = copy.deepcopy(settings if isinstance(settings, dict) else (get_system_settings_sync() or {}))
    enabled = _bool_setting(runtime_settings, "auto_listing_translation_enabled", True) if automatic else True
    fallback_enabled = _bool_setting(runtime_settings, "translation_fallback_enabled", False)
    setting_keys = ("translation_model", "translation_fallback") if fallback_enabled else ("translation_model",)
    return await _resolve_model_feature_state(
        settings=runtime_settings,
        enabled=enabled,
        setting_keys=setting_keys,
        cache_namespace=f"translation:{'automatic' if automatic else 'manual'}",
        resolver=lambda: _resolve_primary_or_fallback_runtime(
            primary_key="translation_model",
            fallback_key="translation_fallback",
            fallback_enabled=fallback_enabled,
            default_temperature=0.1,
            default_max_tokens=1200,
        ),
    )


async def resolve_subjective_scoring_state(settings: dict[str, Any] | None = None) -> AiFeatureState:
    runtime_settings = copy.deepcopy(settings if isinstance(settings, dict) else (get_system_settings_sync() or {}))
    enabled = _bool_setting(runtime_settings, "ai_subjective_scoring_enabled", False)
    return await _resolve_model_feature_state(
        settings=runtime_settings,
        enabled=enabled,
        setting_keys=("score_model",),
        cache_namespace="subjective_scoring",
        resolver=lambda: get_runtime_from_system_settings(
            setting_key="score_model",
            default_provider="ollama",
            default_model="",
            default_api_base="http://localhost:11434",
            default_temperature=0.1,
            default_max_tokens=150,
        ),
    )


async def resolve_ai_policy_status(settings: dict[str, Any] | None = None) -> AiPolicyStatus:
    runtime_settings = copy.deepcopy(settings if isinstance(settings, dict) else (get_system_settings_sync() or {}))
    global_ai = resolve_global_ai_state(runtime_settings)
    writing = await resolve_writing_state(runtime_settings)
    auto_summary = await resolve_auto_summary_state(runtime_settings)
    auto_translation = await resolve_translation_state(automatic=True, settings=runtime_settings)
    reader_translation = await resolve_translation_state(automatic=False, settings=runtime_settings)
    subjective = await resolve_subjective_scoring_state(runtime_settings)
    return AiPolicyStatus(
        global_ai=global_ai,
        writing=writing,
        auto_summary=auto_summary,
        auto_listing_translation=auto_translation,
        reader_translation=reader_translation,
        subjective_scoring=subjective,
        hard_disabled=ai_hard_disabled(),
        paused=ai_processing_paused(runtime_settings),
    )


def product_ai_flag_enabled(key: str, default: bool) -> bool:
    """Synchronous product-flag helper for cheap preflight checks."""

    settings = get_system_settings_sync() or {}
    if _global_block(settings):
        return False
    return _bool_setting(settings, key, default)
