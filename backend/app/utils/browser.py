"""Backwards-compatible re-export.

.. deprecated::
    The canonical home for the shared headless-browser /
    Playwright-driver pool (``get_browser_context``,
    ``local_playwright_fetch_prefs``, ``shutdown_browser_pool``, the
    semaphore + persistent-context locks) is now
    :mod:`app.platform.browser.pool`. Phase 5 step 7 of the module
    refactor moved the implementation out of ``app.utils`` because
    the browser pool is platform-level fetch infrastructure used by
    every Playwright-backed collector, not a generic utility.

    This file remains as a re-export shim. The handful of business
    callers (collectors, ``app.main`` shutdown, the
    ``test_browser_playwright_prefs.py`` import surface) continue
    to import via this shim path; bulk migration is deferred to
    Phase 7. New code MUST import from
    :mod:`app.platform.browser.pool` directly — and especially new
    ``patch`` targets in tests.
"""

from app.platform.browser.pool import *  # noqa: F401,F403 — re-export
from app.platform.browser.pool import (  # noqa: F401 — explicit (private state used by tests)
    MAX_CONCURRENT_BROWSERS,
    _browser_semaphore,
    _is_patchright_active,
    _recommended_launch_args,
    _runtime_default_channel,
)
