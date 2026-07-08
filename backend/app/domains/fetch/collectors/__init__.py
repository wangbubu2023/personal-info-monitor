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

from app.features import PODCAST_DISABLED_DETAIL, PODCAST_SOURCES_ENABLED


def _load_collector_class(source_type: str):
    if source_type == "website":
        from app.domains.fetch.collectors.website import WebsiteCollector

        return WebsiteCollector
    if source_type == "rss":
        from app.domains.fetch.collectors.rss import RSSCollector

        return RSSCollector
    if source_type == "x":
        from app.domains.fetch.collectors.x_twitter import XCollector

        return XCollector
    if source_type == "youtube":
        from app.domains.fetch.collectors.youtube import YouTubeCollector

        return YouTubeCollector
    if source_type == "podcast":
        from app.domains.fetch.collectors.podcast import PodcastCollector

        return PodcastCollector
    return None


def get_collector(source_type: str):
    """Factory function to get the appropriate collector for a source type."""
    if source_type == "podcast" and not PODCAST_SOURCES_ENABLED:
        raise ValueError(PODCAST_DISABLED_DETAIL)

    collector_class = _load_collector_class(source_type)
    if not collector_class:
        raise ValueError(f"Unknown source type: {source_type}")

    return collector_class()


def __getattr__(name: str):
    if name == "BaseCollector":
        from app.domains.fetch.collectors.base import BaseCollector

        return BaseCollector
    mapping = {
        "PodcastCollector": "podcast",
        "RSSCollector": "rss",
        "WebsiteCollector": "website",
        "XCollector": "x",
        "YouTubeCollector": "youtube",
    }
    if name in mapping:
        collector_class = _load_collector_class(mapping[name])
        if collector_class is not None:
            return collector_class
    raise AttributeError(name)


__all__ = [
    "BaseCollector",
    "get_collector",
    "PodcastCollector",
    "RSSCollector",
    "WebsiteCollector",
    "XCollector",
    "YouTubeCollector",
]
