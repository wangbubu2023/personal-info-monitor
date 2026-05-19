"""Backwards-compatible facade for fetch-auth helpers.

The actual implementations have moved to:

* ``app.domains.fetch.auth.credentials.try_parse_auth_credentials``
* ``app.domains.fetch.auth.refresh.maybe_refresh_auth_cookies``
* ``app.domains.fetch.auth.warnings.auth_warning_entry``
* ``app.domains.fetch.auth.warnings.cookie_hydration_warning_entry``
* ``app.platform.auth.cookies.cookies_appear_valid``
* ``app.platform.browser.session_runtime.build_browser_session_runtime``
* ``app.platform.browser.login_capture.login_and_capture_cookies``

This module remains as a re-export facade so existing app callers and the
extensive ``unittest.mock.patch("app.tasks.fetch_auth_helpers.*")`` test
surface keep working through Phase 7. Private helpers exposed by name
(``_login_and_capture_cookies``, ``_DEFAULT_*``, ``_domain_match``,
``_BROWSER_SESSION_AUTH_TTL_DAYS``) are re-bound with their historical
underscore names so existing ``monkeypatch.setattr`` calls keep resolving.

.. deprecated::
   Import from the canonical locations above. This facade will be removed in
   Phase 7 after the test patch targets have been migrated.
"""

from __future__ import annotations

from app.domains.fetch.auth.credentials import try_parse_auth_credentials
from app.domains.fetch.auth.refresh import _DEFAULT_LOGIN_URLS, maybe_refresh_auth_cookies
from app.domains.fetch.auth.warnings import auth_warning_entry, cookie_hydration_warning_entry
from app.platform.auth.cookies import cookies_appear_valid, domain_match as _domain_match
from app.platform.browser.login_capture import (
    _DEFAULT_PASSWORD_SELECTORS,
    _DEFAULT_SUBMIT_SELECTORS,
    _DEFAULT_USERNAME_SELECTORS,
    _find_first_selector,
    _page_has_captcha,
    login_and_capture_cookies as _login_and_capture_cookies,
)
from app.platform.browser.session_runtime import (
    BROWSER_SESSION_AUTH_TTL_DAYS as _BROWSER_SESSION_AUTH_TTL_DAYS,
    build_browser_session_runtime,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "auth_warning_entry",
    "build_browser_session_runtime",
    "cookie_hydration_warning_entry",
    "cookies_appear_valid",
    "maybe_refresh_auth_cookies",
    "try_parse_auth_credentials",
]
