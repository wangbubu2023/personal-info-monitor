"""Platform-level browser session primitives.

This package owns headless-browser side-effects that any domain may use:

* ``session_runtime`` — load a persistent BrowserSession profile into a runtime
  dict (cookie freshness, profile/storage_state presence, etc.).
* ``login_capture`` — drive Playwright through a generic username/password
  login form and return the captured cookie jar.

Domain code (e.g. ``app.domains.fetch.auth.refresh``) consumes these helpers
without ever touching Playwright directly.
"""

from app.platform.browser.login_capture import login_and_capture_cookies
from app.platform.browser.session_runtime import (
    BROWSER_SESSION_AUTH_TTL_DAYS,
    build_browser_session_runtime,
)

__all__ = [
    "BROWSER_SESSION_AUTH_TTL_DAYS",
    "build_browser_session_runtime",
    "login_and_capture_cookies",
]
