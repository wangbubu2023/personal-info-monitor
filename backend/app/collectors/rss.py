"""Backwards-compatible facade for :class:`RSSCollector`.

The implementation has moved to :mod:`app.domains.fetch.collectors.rss`.
This shim re-exports the collector so existing imports and test patches
continue to resolve to the same class.

.. deprecated::
   Import :class:`RSSCollector` from
   :mod:`app.domains.fetch.collectors.rss` (or via the collector factory
   ``app.collectors.get_collector("rss")``). This shim will be removed in
   Phase 7.
"""

from app.domains.fetch.collectors.rss import RSSCollector

__all__ = ["RSSCollector"]
