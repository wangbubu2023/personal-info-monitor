"""Compatibility shim — application settings moved to :mod:`app.platform.config.settings`.

Phase 5 step 10 of the modular refactor relocated the canonical implementation
of :class:`Settings`, :func:`get_settings`, :func:`bootstrap_runtime_environment`
and the CORS-origin parsing helpers under ``app.platform.config.settings``. This
module is kept as a re-export bridge so existing callers (and external test
patches targeting ``app.config.get_settings`` / ``app.config.bootstrap_runtime_environment``)
continue to work unchanged until they are migrated in Phase 7.

The re-exports cover both the public surface and the underscore-prefixed
internal helpers, so downstream code that previously reached for
``app.config._default_data_dir`` / ``app.config._ensure_runtime_secrets`` keeps
resolving the same callables.
"""

from app.platform.config.settings import (
    CorsOriginConfigError,
    Settings,
    _default_cors_origins,
    _default_data_dir,
    _ensure_runtime_secrets,
    _read_runtime_secrets,
    _RUNTIME_SECRETS_FILENAME,
    _runtime_secrets_path,
    _write_runtime_secrets,
    bootstrap_runtime_environment,
    effective_cors_origins,
    get_settings,
    parse_cors_origins,
)

__all__ = [
    "CorsOriginConfigError",
    "Settings",
    "bootstrap_runtime_environment",
    "effective_cors_origins",
    "get_settings",
    "parse_cors_origins",
]
