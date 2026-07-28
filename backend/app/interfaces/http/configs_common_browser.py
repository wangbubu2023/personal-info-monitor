"""Backwards-compatible facade for browser-session + Playwright helpers.

The implementations have moved to:

* ``app.platform.browser.profiles``       — ``profiles_root``, ``slugify_profile_name``
* ``app.platform.browser.hosts``          — ``is_x_host`` (+ ``_X_HOSTS``)
* ``app.platform.browser.bootstrap``      — ``run_browser_bootstrap``
* ``app.platform.browser.validation``     — ``run_browser_validation`` + helpers
* ``app.domains.fetch.auth.browser``      — ``serialize_browser_session``,
  ``ensure_x_shared_auth_config``, ``sync_cookies_to_auth_config``,
  ``bind_browser_session_to_sources``

This module is kept as a re-export shim so existing callers
(``api.configs_common`` aggregate facade, ``api.configs_browser`` router, and
the ``test_configs_common_browser.py`` patch surface) continue to import from
the original path through Phase 7.

.. deprecated::
   Import from the canonical platform / domain locations above. This shim
   will be removed once test patches have been migrated (Phase 7).
"""

from __future__ import annotations

from app.domains.fetch.auth.browser import (
    bind_browser_session_to_sources,
    ensure_x_shared_auth_config,
    serialize_browser_session,
    sync_cookies_to_auth_config,
)
from app.platform.browser.bootstrap import (
    _BROWSER_USER_AGENT,
    _require_playwright,
    run_browser_bootstrap,
)
from app.platform.browser.hosts import _X_HOSTS, is_wsj_host, is_x_host
from app.platform.browser.profiles import profiles_root, slugify_profile_name
from app.platform.browser.validation import (
    _run_x_cookie_validation,
    _has_wsj_authenticated_session,
    _run_wsj_session_validation,
    _wsj_auth_cookie_names,
    _validation_html_for_wall_scan,
    _validation_paragraph_count,
    browser_validation_probe_url,
    run_browser_validation,
)

__all__ = [
    "bind_browser_session_to_sources",
    "browser_validation_probe_url",
    "ensure_x_shared_auth_config",
    "is_wsj_host",
    "is_x_host",
    "profiles_root",
    "run_browser_bootstrap",
    "run_browser_validation",
    "serialize_browser_session",
    "slugify_profile_name",
    "sync_cookies_to_auth_config",
]
