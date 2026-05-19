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

from app.domains.fetch.auth.credentials import try_parse_auth_credentials
from app.domains.fetch.auth.refresh import maybe_refresh_auth_cookies
from app.domains.fetch.auth.warnings import (
    auth_warning_entry,
    cookie_hydration_warning_entry,
)

__all__ = [
    "auth_warning_entry",
    "cookie_hydration_warning_entry",
    "maybe_refresh_auth_cookies",
    "try_parse_auth_credentials",
]
