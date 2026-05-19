"""Backwards-compatible facade for :class:`YouTubeCollector`.

Implementation lives at :mod:`app.domains.fetch.collectors.youtube`.

.. deprecated::
   Import :class:`YouTubeCollector` from
   :mod:`app.domains.fetch.collectors.youtube` directly (or via the
   collector factory ``app.collectors.get_collector("youtube")``). This
   shim will be removed in Phase 7.
"""

from app.domains.fetch.collectors.youtube import YouTubeCollector

__all__ = ["YouTubeCollector"]
