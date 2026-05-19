"""fetch-domain collector package.

All per-source-type collectors live here as of Phase 2.9:

* ``base``           — shared :class:`BaseCollector` (Phase 2.6)
* ``rss``            — :class:`RSSCollector` (Phase 2.6)
* ``website``        — :class:`WebsiteCollector` + helpers/parser (Phase 2.7)
* ``x_twitter``      — :class:`XCollector` + text/formatters (Phase 2.8)
* ``youtube``        — :class:`YouTubeCollector` (Phase 2.9)
* ``podcast``        — :class:`PodcastCollector` (Phase 2.9)

The legacy ``app.collectors.*`` modules remain as re-export shims so
existing imports and test ``unittest.mock.patch`` targets keep working
through Phase 7. New code should import from
``app.domains.fetch.collectors`` or use the ``app.collectors.get_collector``
factory.
"""

from app.domains.fetch.collectors.base import BaseCollector
from app.domains.fetch.collectors.podcast import PodcastCollector
from app.domains.fetch.collectors.rss import RSSCollector
from app.domains.fetch.collectors.website import WebsiteCollector
from app.domains.fetch.collectors.x_twitter import XCollector
from app.domains.fetch.collectors.youtube import YouTubeCollector

__all__ = [
    "BaseCollector",
    "PodcastCollector",
    "RSSCollector",
    "WebsiteCollector",
    "XCollector",
    "YouTubeCollector",
]
