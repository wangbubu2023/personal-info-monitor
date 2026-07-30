"""Platform-level browser session primitives.

Sub-modules:

* ``session_runtime`` — load a persistent BrowserSession profile into a runtime
  dict (cookie freshness, profile/storage_state presence, etc.).
* ``login_capture`` — drive Playwright through a generic username/password
  login form and return the captured cookie jar.
* ``profiles`` — filesystem helpers for persistent profile directories.
* ``hosts`` — site-family detection (``x.com``/``twitter.com`` equivalence).
* ``bootstrap`` — persistent-context Playwright bootstrap that captures the
  post-login cookie jar (headful UX + headless settle wait).
* ``validation`` — profile validation against the target site (paywall
  article-paragraph heuristic + X cookie heuristic).
* ``pool`` — long-lived Playwright driver + Chromium ``Browser`` pool that
  hands out disposable ``BrowserContext`` per fetch (Phase 5 step 7
  relocation from ``app.utils.browser``).
* ``playwright_runtime`` — patchright/playwright backend selector
  (Phase 5 step 7 relocation from ``app.utils.playwright_runtime``).
* ``playwright_stealth`` — anti-fingerprint init script
  (Phase 5 step 7 relocation from ``app.utils.playwright_stealth``).

Domain code (e.g. ``app.domains.fetch.auth``) consumes these helpers without
ever touching Playwright / Chromium directly.
"""

from app.platform.browser.bootstrap import HeadfulBrowserUnavailableError, run_browser_bootstrap
from app.platform.browser.hosts import (
    X_REQUIRED_AUTH_COOKIES,
    is_wsj_host,
    is_x_host,
    missing_x_auth_cookies,
    x_auth_cookie_names,
)
from app.platform.browser.login_capture import login_and_capture_cookies
from app.platform.browser.profiles import profiles_root, slugify_profile_name
from app.platform.browser.session_runtime import (
    BROWSER_SESSION_AUTH_TTL_DAYS,
    build_browser_session_runtime,
)
from app.platform.browser.validation import (
    browser_validation_probe_url,
    run_browser_validation,
)

__all__ = [
    "BROWSER_SESSION_AUTH_TTL_DAYS",
    "browser_validation_probe_url",
    "build_browser_session_runtime",
    "HeadfulBrowserUnavailableError",
    "is_wsj_host",
    "is_x_host",
    "login_and_capture_cookies",
    "missing_x_auth_cookies",
    "profiles_root",
    "run_browser_bootstrap",
    "run_browser_validation",
    "slugify_profile_name",
    "X_REQUIRED_AUTH_COOKIES",
    "x_auth_cookie_names",
]
