"""Data collectors for different source types."""

from app.domains.fetch.collectors import BaseCollector, RSSCollector
from app.collectors.website import WebsiteCollector
from app.collectors.x_twitter import XCollector
from app.collectors.youtube import YouTubeCollector
from app.collectors.podcast import PodcastCollector
from app.features import PODCAST_DISABLED_DETAIL, PODCAST_SOURCES_ENABLED


def get_collector(source_type: str) -> BaseCollector:
    """Factory function to get the appropriate collector for a source type."""
    if source_type == "podcast" and not PODCAST_SOURCES_ENABLED:
        raise ValueError(PODCAST_DISABLED_DETAIL)

    collectors = {
        "website": WebsiteCollector,
        "rss": RSSCollector,
        "x": XCollector,
        "youtube": YouTubeCollector,
        "podcast": PodcastCollector,
    }
    
    collector_class = collectors.get(source_type)
    if not collector_class:
        raise ValueError(f"Unknown source type: {source_type}")
    
    return collector_class()


__all__ = [
    "BaseCollector",
    "WebsiteCollector",
    "RSSCollector",
    "XCollector",
    "YouTubeCollector",
    "PodcastCollector",
    "get_collector",
]
