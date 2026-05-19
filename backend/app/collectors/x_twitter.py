"""Backwards-compatible facade for :class:`XCollector`.

Implementation lives at :mod:`app.domains.fetch.collectors.x_twitter`.

.. deprecated::
   Import :class:`XCollector` from
   :mod:`app.domains.fetch.collectors.x_twitter` directly (or via the
   collector factory ``app.collectors.get_collector("x")``). This shim
   will be removed in Phase 7.
"""

from app.domains.fetch.collectors.x_twitter import XCollector

__all__ = ["XCollector"]
