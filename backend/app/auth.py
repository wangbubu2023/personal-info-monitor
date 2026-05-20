"""Backwards-compatible re-export.

.. deprecated::
    The canonical home for the ``X-API-Key`` FastAPI dependency
    (``verify_api_key``) is now :mod:`app.platform.auth.api_key`.
    Phase 5 step 8 of the module refactor moved the implementation
    out of ``app`` because API-key auth is platform-level security
    infrastructure used by every router, not application code.

    This file remains as a thin re-export shim. The handful of call
    sites that currently import from ``app.auth`` (``app.api``,
    ``app.main``, ``tests/conftest.py``,
    ``tests/test_configs_browser.py``) continue to use this path;
    bulk migration is deferred to Phase 7. New code MUST import
    from :mod:`app.platform.auth.api_key` directly — and especially
    new ``patch`` targets in tests, because the production
    ``verify_api_key`` reads ``get_settings`` from the canonical
    module (rebinding the shim's ``get_settings`` attribute is a
    no-op for the canonical caller's local lookup).
"""

from app.platform.auth.api_key import (  # noqa: F401 — re-export
    _api_key_header,
    verify_api_key,
)

# ``get_settings`` is re-exported so legacy ``patch("app.auth.get_settings")``
# sites can still find the attribute on this module (and at least keep the
# import valid). Note that patching this attribute does NOT replace what the
# canonical ``verify_api_key`` actually reads — see the deprecation note
# above.
from app.config import get_settings  # noqa: F401 — legacy patch-target compatibility

__all__ = ["verify_api_key"]
