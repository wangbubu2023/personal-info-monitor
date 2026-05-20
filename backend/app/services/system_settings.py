"""Backwards-compatible re-export.

.. deprecated::
    The canonical home for system-settings persistence and runtime
    access helpers is now :mod:`app.platform.config.system_settings`.
    Phase 5 step 2 of the module refactor moved the implementation
    out of ``app.services`` because system settings are platform-level
    configuration consumed across every domain (ingest filters, enrich
    summaries/translation, hourly digest prompt, sources limits) — not
    a single business service.

    This file remains as a thin re-export shim so existing imports
    (and ``patch("app.services.system_settings.*")`` targets in tests)
    keep working. Phase 7 removes it. New code MUST import from
    :mod:`app.platform.config.system_settings` directly.

    Note: ``from ... import *`` does NOT carry underscore-prefixed
    symbols. Underscore helpers used by tests (``_apply_patch``,
    ``_cache_get``, ``_cache_set``, ``_cache_invalidate``,
    ``_mask_sensitive``, ``_normalize_fallback_settings``,
    ``_coerce_persisted_settings``, ``_merge_dict``,
    ``_parse_bool_value``, ``_coerce_int``) are therefore re-exported
    explicitly below.
"""

from app.platform.config.system_settings import (  # noqa: F401 — re-export
    DEFAULT_SYSTEM_SETTINGS,
    HOURLY_DIGEST_DEFAULT_PROMPT,
    SYSTEM_SETTINGS_KEY,
    _apply_patch,
    _cache_get,
    _cache_invalidate,
    _cache_set,
    _coerce_int,
    _coerce_persisted_settings,
    _mask_sensitive,
    _merge_dict,
    _normalize_fallback_settings,
    _parse_bool_value,
    effective_hourly_digest_prompt,
    get_system_settings_async,
    get_system_settings_for_response,
    get_system_settings_sync,
    invalidate_system_settings_cache,
    normalize_hourly_digest_content_types,
    normalize_hourly_digest_window_hours,
    update_system_settings_async,
)

__all__ = [
    "DEFAULT_SYSTEM_SETTINGS",
    "HOURLY_DIGEST_DEFAULT_PROMPT",
    "SYSTEM_SETTINGS_KEY",
    "effective_hourly_digest_prompt",
    "get_system_settings_async",
    "get_system_settings_for_response",
    "get_system_settings_sync",
    "invalidate_system_settings_cache",
    "normalize_hourly_digest_content_types",
    "normalize_hourly_digest_window_hours",
    "update_system_settings_async",
]
