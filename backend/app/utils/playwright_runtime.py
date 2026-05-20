"""Backwards-compatible re-export.

.. deprecated::
    The canonical home for the patchright/playwright backend
    selector (``async_playwright``, ``backend_name``,
    ``default_channel``, ``is_patchright_active``,
    ``recommended_launch_args``, ``timeout_error_types``) is now
    :mod:`app.platform.browser.playwright_runtime`. Phase 5 step 7
    of the module refactor moved the implementation out of
    ``app.utils`` because the backend selector lives next to the
    rest of the platform browser machinery.

    This file remains as a re-export shim — the website / X /
    doctor / bootstrap call sites continue to import via this path
    until Phase 7. New code MUST import from
    :mod:`app.platform.browser.playwright_runtime` directly.

    Note: ``from ... import *`` does NOT carry underscore-prefixed
    names. The backend cache (``_cached_backend`` /
    ``_cached_timeout_error``) and the ``_load_backend`` helper are
    re-exported explicitly below so tests that reset the cache via
    ``monkeypatch`` keep targeting the same module identity.
"""

from app.platform.browser.playwright_runtime import *  # noqa: F401,F403 — re-export
from app.platform.browser.playwright_runtime import (  # noqa: F401 — explicit (private cache)
    _cached_backend,
    _cached_timeout_error,
    _load_backend,
)
