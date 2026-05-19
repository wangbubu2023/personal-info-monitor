"""fetch-domain collector package.

Phase 2.6 onwards moves the per-source-type collectors out of
``app.collectors`` and into this package. Migration order (one PR each):

* Phase 2.6 — ``base`` + ``rss``
* Phase 2.7 — ``website``
* Phase 2.8 — ``x``
* Phase 2.9 — ``youtube`` + ``podcast``

Until every collector lives here, ``app.collectors.*`` keeps re-export
shims pointing back to the new locations so existing imports and test
``unittest.mock.patch`` targets keep working through Phase 7.
"""

from app.domains.fetch.collectors.base import BaseCollector
from app.domains.fetch.collectors.rss import RSSCollector

__all__ = ["BaseCollector", "RSSCollector"]
