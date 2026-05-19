"""Backwards-compatible facade for :class:`BaseCollector`.

The implementation has moved to
:mod:`app.domains.fetch.collectors.base`. This shim re-exports
``BaseCollector`` and the module-level helpers (``utcnow_naive``,
``assert_public_http_target``, ``logger``) that existing tests patch via
``unittest.mock.patch("app.collectors.base.<name>", ...)``.

.. deprecated::
   Import from :mod:`app.domains.fetch.collectors.base` directly. This
   shim will be removed in Phase 7 after the patch targets have been
   migrated.
"""

from app.domains.fetch.collectors.base import (
    BaseCollector,
    assert_public_http_target,
    logger,
    utcnow_naive,
)

__all__ = [
    "BaseCollector",
    "assert_public_http_target",
    "logger",
    "utcnow_naive",
]
