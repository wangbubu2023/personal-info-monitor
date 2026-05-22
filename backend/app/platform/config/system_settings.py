"""System settings persistence and runtime access helpers."""

import copy
import threading
import time
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.persistence.database import SessionLocal
from app.models.system_setting import SystemSetting
from app.platform.observability.logger import get_logger

logger = get_logger(__name__)

_HOURLY_DIGEST_ALLOWED_TYPES = frozenset({"website", "rss", "x", "youtube", "podcast"})
_HOURLY_DIGEST_PROMPT_MAX = 8000
_HOURLY_DIGEST_WINDOW_HOURS_DEFAULT = 3

# 用户未保存过任何文案时，GET 设置与整点任务均使用此默认（可在「任务提示」页看到并编辑后落库）
HOURLY_DIGEST_DEFAULT_PROMPT = """【选稿】从本次简报窗口内已入库的候选条目中，挑出最值得写进综述的稿件。优先：对用户决策或认知有明显信息增益、重大突发与时效强、存在多源互证的热点。排除：纯标题党、重复灌水、几乎没有有效信息的条目。

【综述】写成中文「私人秘书式」资讯综述：语气克制、信息密度高，像在向用户口头汇报本窗口最值得关心的动态。不要用 1.2.3. 清单体或连续多个小节标题堆叠；用 2～5 个自然段连贯叙述，段与段之间空一行。在叙述中自然穿插素材里给出的 Markdown 本地链接（形式为 [可见文案](/reader/内容ID)），至少引用超过半数的入选素材；链接必须原样复制素材中的路径，禁止改用外站 http(s) 链接。不要编造素材中没有的信息。"""

SYSTEM_SETTINGS_KEY = "global"
_CACHE_TTL_SECONDS = 30
_cache_lock = threading.Lock()
_cache_value: Dict[str, Any] | None = None
_cache_deadline = 0.0

DEFAULT_SYSTEM_SETTINGS: Dict[str, Any] = {
    "ai_model": {
        "provider": "ollama",
        "model": "",
        "api_base": "http://localhost:11434",
        "temperature": 0.7,
        "max_tokens": 1000,
        "ollama_num_ctx": 8192,
        "ollama_no_think": False,
    },
    "translation_model": {
        "provider": "ollama",
        "model": "",
        "api_base": "http://localhost:11434",
        "ollama_num_ctx": 2048,
        "ollama_no_think": True,
    },
    "atom_model": {
        "provider": "ollama",
        "model": "",
        "api_base": "http://localhost:11434",
        "temperature": 0.1,
        "max_tokens": 4000,
        "ollama_num_ctx": 8192,
        "ollama_no_think": False,
    },
    "score_model": {
        "provider": "ollama",
        "model": "",
        "api_base": "http://localhost:11434",
        "temperature": 0.1,
        "max_tokens": 150,
        "ollama_num_ctx": 2048,
        "ollama_no_think": True,
    },
    "translation_enabled": True,
    "title_translation_enabled": True,
    "auto_translate_language": "zh-CN",
    "summarization_enabled": True,
    "translation_fallback_enabled": False,
    "translation_fallback": {"provider": "openai", "model": "gpt-4o-mini"},
    "summarization_fallback_enabled": False,
    "summarization_fallback": {"provider": "openai", "model": "gpt-4o-mini"},
    "email_notifications_enabled": False,
    "score_lab_enabled": False,
    "limits": {
        "max_sources": 200,
        "max_digest_candidates": 12,
        "max_hourly_digest_input_items": 200,
    },
    "hourly_digest": {
        "prompt": "",
        "content_types": ["website", "rss"],
        "window_hours": _HOURLY_DIGEST_WINDOW_HOURS_DEFAULT,
    },
}

_SETTINGS_BOOL_KEYS = (
    "translation_enabled",
    "title_translation_enabled",
    "summarization_enabled",
    "translation_fallback_enabled",
    "summarization_fallback_enabled",
    "email_notifications_enabled",
    "score_lab_enabled",
)
_AI_MODEL_KEYS = ("provider", "model", "api_base", "temperature", "max_tokens", "api_key", "ollama_num_ctx", "ollama_no_think")
_TRANS_MODEL_KEYS = ("provider", "model", "api_base", "api_key", "ollama_num_ctx", "ollama_no_think")
_ATOM_MODEL_KEYS = ("provider", "model", "api_base", "temperature", "max_tokens", "api_key", "ollama_num_ctx", "ollama_no_think")
_LIMIT_RULES = {
    "max_sources": (200, 1, 5000),
    "max_digest_candidates": (12, 3, 30),
    "max_hourly_digest_input_items": (200, 20, 2000),
}

_FALLBACK_MODEL_KEYS = ("provider", "model")

_LEGACY_BOOL_KEYS = (
    "translation_cloud_fallback_enabled",
    "summarization_cloud_fallback_enabled",
)


def _parse_bool_value(val: Any) -> bool:
    """Coerce JSON/body bools; avoid truthiness traps (e.g. str)."""
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    if isinstance(val, (int, float)):
        return bool(val) and val != 0
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes", "on")
    return False


def _normalize_fallback_settings(s: Dict[str, Any]) -> None:
    """Migrate legacy *cloud_fallback* flags and ensure fallback model dicts exist."""
    if not isinstance(s, dict):
        return
    if "translation_fallback_enabled" not in s and "translation_cloud_fallback_enabled" in s:
        s["translation_fallback_enabled"] = bool(s.get("translation_cloud_fallback_enabled"))
    if "summarization_fallback_enabled" not in s and "summarization_cloud_fallback_enabled" in s:
        s["summarization_fallback_enabled"] = bool(s.get("summarization_cloud_fallback_enabled"))
    if not isinstance(s.get("translation_fallback"), dict):
        s["translation_fallback"] = {"provider": "openai", "model": "gpt-4o-mini"}
    else:
        tf = s["translation_fallback"]
        tf.setdefault("provider", "openai")
        tf.setdefault("model", "gpt-4o-mini")
    if not isinstance(s.get("summarization_fallback"), dict):
        s["summarization_fallback"] = {"provider": "openai", "model": "gpt-4o-mini"}
    else:
        sf = s["summarization_fallback"]
        sf.setdefault("provider", "openai")
        sf.setdefault("model", "gpt-4o-mini")


def _coerce_int(value: Any, default: int, *, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(min_value, min(max_value, parsed))


def effective_hourly_digest_prompt(hd: Any) -> str:
    """整点任务使用的提示词：已保存的 prompt → 旧版两字段合并 → 内置默认。"""
    if not isinstance(hd, dict):
        return HOURLY_DIGEST_DEFAULT_PROMPT
    p = str(hd.get("prompt") or "").strip()
    if p:
        return p
    imp = str(hd.get("importance_prompt") or "").strip()
    syn = str(hd.get("synthesis_prompt") or "").strip()
    legacy = "\n\n".join(x for x in [imp, syn] if x)
    if legacy:
        return legacy
    return HOURLY_DIGEST_DEFAULT_PROMPT


def normalize_hourly_digest_content_types(settings: Dict[str, Any]) -> list[str]:
    """Types of Content rows scanned for hourly digest (matches SourceType / content_type)."""
    hd = settings.get("hourly_digest") if isinstance(settings.get("hourly_digest"), dict) else {}
    raw = hd.get("content_types")
    if isinstance(raw, list):
        out = [str(x).strip() for x in raw if str(x).strip() in _HOURLY_DIGEST_ALLOWED_TYPES]
        if out:
            return out
    return list(DEFAULT_SYSTEM_SETTINGS["hourly_digest"]["content_types"])


def normalize_hourly_digest_window_hours(settings: Dict[str, Any]) -> int:
    """Completed-hour window length used for digest generation."""
    hd = settings.get("hourly_digest") if isinstance(settings.get("hourly_digest"), dict) else {}
    raw = hd.get("window_hours") if isinstance(hd, dict) else None
    return _coerce_int(
        raw,
        _HOURLY_DIGEST_WINDOW_HOURS_DEFAULT,
        min_value=1,
        max_value=24,
    )


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


def _normalize_ollama_model_fields(target: dict, *, default_ctx: int) -> None:
    if "ollama_num_ctx" in target:
        from app.ai.provider import snap_ollama_num_ctx

        target["ollama_num_ctx"] = snap_ollama_num_ctx(
            _coerce_int(
                target.get("ollama_num_ctx"),
                default_ctx,
                min_value=1024,
                max_value=262144,
            )
        )
    if "ollama_no_think" in target:
        target["ollama_no_think"] = _parse_bool_value(target.get("ollama_no_think"))


def _apply_patch(current: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    updated = copy.deepcopy(current)

    ai_model = patch.get("ai_model")
    if isinstance(ai_model, dict):
        target = updated.setdefault("ai_model", {})
        for key in _AI_MODEL_KEYS:
            if key in ai_model:
                target[key] = ai_model[key]
        _normalize_ollama_model_fields(
            target,
            default_ctx=DEFAULT_SYSTEM_SETTINGS["ai_model"]["ollama_num_ctx"],
        )

    translation_model = patch.get("translation_model")
    if isinstance(translation_model, dict):
        target = updated.setdefault("translation_model", {})
        for key in _TRANS_MODEL_KEYS:
            if key in translation_model:
                target[key] = translation_model[key]
        _normalize_ollama_model_fields(
            target,
            default_ctx=DEFAULT_SYSTEM_SETTINGS["translation_model"]["ollama_num_ctx"],
        )

    atom_model = patch.get("atom_model")
    if isinstance(atom_model, dict):
        target = updated.setdefault("atom_model", {})
        for key in _ATOM_MODEL_KEYS:
            if key in atom_model:
                target[key] = atom_model[key]
        _normalize_ollama_model_fields(
            target,
            default_ctx=DEFAULT_SYSTEM_SETTINGS["atom_model"]["ollama_num_ctx"],
        )

    for fb_name in ("translation_fallback", "summarization_fallback"):
        fb_patch = patch.get(fb_name)
        if isinstance(fb_patch, dict):
            target = updated.setdefault(fb_name, {})
            for key in _FALLBACK_MODEL_KEYS:
                if key in fb_patch:
                    target[key] = fb_patch[key]

    if "auto_translate_language" in patch:
        updated["auto_translate_language"] = patch["auto_translate_language"]

    for key in _SETTINGS_BOOL_KEYS:
        if key in patch:
            updated[key] = _parse_bool_value(patch[key])

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

    hd_patch = patch.get("hourly_digest")
    if isinstance(hd_patch, dict):
        target_hd = updated.setdefault(
            "hourly_digest",
            copy.deepcopy(DEFAULT_SYSTEM_SETTINGS["hourly_digest"]),
        )
        if "prompt" in hd_patch:
            target_hd["prompt"] = str(hd_patch.get("prompt") or "")[:_HOURLY_DIGEST_PROMPT_MAX]
        if "content_types" in hd_patch and isinstance(hd_patch.get("content_types"), list):
            picked = [
                str(x).strip()
                for x in hd_patch["content_types"]
                if str(x).strip() in _HOURLY_DIGEST_ALLOWED_TYPES
            ]
            if picked:
                target_hd["content_types"] = picked
        if "window_hours" in hd_patch:
            target_hd["window_hours"] = _coerce_int(
                hd_patch.get("window_hours"),
                _HOURLY_DIGEST_WINDOW_HOURS_DEFAULT,
                min_value=1,
                max_value=24,
            )

    return updated


def _mask_sensitive(settings: Dict[str, Any]) -> Dict[str, Any]:
    response = copy.deepcopy(settings)
    for field in ("ai_model", "translation_model", "atom_model"):
        model = response.get(field) or {}
        if isinstance(model, dict):
            model["has_api_key"] = bool(model.get("api_key"))
            model.pop("api_key", None)
            response[field] = model
    return response


def get_system_settings_for_response(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Public helper for API response payload.

    hourly_digest.prompt = 用户已保存的文案（可为空；空表示未自定义，整点任务走内置默认）。
    勿将内置默认写回 prompt，否则前端无法区分「未保存」与「保存了与默认相同的全文」。
    hourly_digest.prompt_effective = 任务实际将使用的提示词（自定义 / 旧版双字段 / 内置），只读。
    """
    response = _mask_sensitive(settings)
    hd = response.get("hourly_digest")
    if isinstance(hd, dict):
        hd_out = copy.deepcopy(hd)
        prompt_effective = effective_hourly_digest_prompt(hd_out)
        p = str(hd_out.get("prompt") or "").strip()
        if not p:
            imp = str(hd_out.get("importance_prompt") or "").strip()
            syn = str(hd_out.get("synthesis_prompt") or "").strip()
            legacy = "\n\n".join(x for x in [imp, syn] if x)
            if legacy:
                hd_out["prompt"] = legacy
        hd_out["prompt_effective"] = prompt_effective
        response["hourly_digest"] = hd_out
    return response


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
    _normalize_fallback_settings(merged)
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
    _normalize_fallback_settings(merged)
    _cache_set(merged)
    return copy.deepcopy(merged)


async def update_system_settings_async(db: AsyncSession, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Apply patch and persist merged settings."""
    current = await get_system_settings_async(db, force_refresh=True)
    merged = _apply_patch(current, patch or {})
    _normalize_fallback_settings(merged)
    # 避免新旧键并存时持久化层长期保留 legacy，导致前端 ?? 读到旧 false
    for legacy in _LEGACY_BOOL_KEYS:
        merged.pop(legacy, None)

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
