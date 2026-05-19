"""Backwards-compatible facade for :class:`PodcastCollector`.

Implementation lives at :mod:`app.domains.fetch.collectors.podcast`.

.. deprecated::
   Import :class:`PodcastCollector` from
   :mod:`app.domains.fetch.collectors.podcast` directly (or via the
   collector factory ``app.collectors.get_collector("podcast")``). This
   shim will be removed in Phase 7.
"""

from app.domains.fetch.collectors.podcast import PodcastCollector

__all__ = ["PodcastCollector"]
