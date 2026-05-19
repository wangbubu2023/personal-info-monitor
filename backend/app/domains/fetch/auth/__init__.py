"""fetch-domain authentication facade.

This package owns the business decisions around source authentication:

* ``credentials`` — decrypt and normalise the stored credential blob.
* ``refresh`` — drive a cookie refresh when stored cookies look stale, by
  delegating to ``platform.browser.login_and_capture_cookies``.
* ``warnings`` — surface human-readable auth/cookie diagnostics for the
  per-fetch warning channel consumed by the pipeline.

Lower-level mechanics (Playwright login, generic cookie probing,
``BrowserSession`` runtime hydration) live in ``app.platform.{browser,auth}``.
"""

from app.domains.fetch.auth.browser import (
    bind_browser_session_to_sources,
    ensure_x_shared_auth_config,
    serialize_browser_session,
    sync_cookies_to_auth_config,
)
from app.domains.fetch.auth.credentials import try_parse_auth_credentials
from app.domains.fetch.auth.refresh import maybe_refresh_auth_cookies
from app.domains.fetch.auth.warnings import (
    auth_warning_entry,
    cookie_hydration_warning_entry,
)

__all__ = [
    "auth_warning_entry",
    "bind_browser_session_to_sources",
    "cookie_hydration_warning_entry",
    "ensure_x_shared_auth_config",
    "maybe_refresh_auth_cookies",
    "serialize_browser_session",
    "sync_cookies_to_auth_config",
    "try_parse_auth_credentials",
]
