"""Backwards-compatible re-export.

.. deprecated::
    The canonical home for the Playwright anti-fingerprint init
    script (``stealth_init_script`` — the navigator.webdriver,
    window.chrome, plugins, WebGL renderer patches that paywall
    sites key on) is now
    :mod:`app.platform.browser.playwright_stealth`. Phase 5 step 7
    of the module refactor moved the implementation out of
    ``app.utils`` so the stealth script sits next to the rest of
    the platform browser machinery.

    This file remains as a thin re-export shim. The website
    collector + bootstrap + validation call sites continue to
    import via this path; bulk migration is deferred to Phase 7.
"""

from app.platform.browser.playwright_stealth import stealth_init_script  # noqa: F401 — re-export

__all__ = ["stealth_init_script"]
