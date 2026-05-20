"""Shared helpers for configuration API modules (facade).

Historically this module hosted every helper used by the configuration API
routers (API-key CRUD, AuthConfig CRUD, browser sessions). The 2026-04-20
audit flagged it as a single 400-line grab-bag touching three concerns;
we split the bulk into three sibling modules and keep this file as a thin
re-export facade so that downstream callers (``configs_api_auth``,
``configs_browser``, ``services.api_config_credentials`` …) keep working
without changes.

The three sibling modules own:

* ``configs_common_auth``    — API-key + AuthConfig serialisation / decrypt
* ``configs_common_cookies`` — cookie normalisation + auth→source binding
* ``configs_common_browser`` — browser sessions + Playwright orchestration
"""

from app.interfaces.http.configs_common_auth import (  # noqa: F401 — re-export
    decrypt_api_credentials,
    decrypt_auth_credentials,
    has_any_credentials,
    is_shared_x_cookie_config,
    mask_api_key,
    serialize_api_config,
    serialize_auth_config,
)
from app.interfaces.http.configs_common_browser import (  # noqa: F401 — re-export
    bind_browser_session_to_sources,
    ensure_x_shared_auth_config,
    is_x_host,
    profiles_root,
    run_browser_bootstrap,
    run_browser_validation,
    serialize_browser_session,
    slugify_profile_name,
    sync_cookies_to_auth_config,
)
from app.interfaces.http.configs_common_cookies import (  # noqa: F401 — re-export
    bind_auth_config_to_all_x_sources,
    bind_auth_config_to_sources,
    extract_auth_cookies_for_host,
    normalize_cookies_input,
)

__all__ = [
    "decrypt_api_credentials",
    "decrypt_auth_credentials",
    "has_any_credentials",
    "is_shared_x_cookie_config",
    "mask_api_key",
    "serialize_api_config",
    "serialize_auth_config",
    "bind_browser_session_to_sources",
    "ensure_x_shared_auth_config",
    "is_x_host",
    "profiles_root",
    "run_browser_bootstrap",
    "run_browser_validation",
    "serialize_browser_session",
    "slugify_profile_name",
    "sync_cookies_to_auth_config",
    "bind_auth_config_to_all_x_sources",
    "bind_auth_config_to_sources",
    "extract_auth_cookies_for_host",
    "normalize_cookies_input",
]
