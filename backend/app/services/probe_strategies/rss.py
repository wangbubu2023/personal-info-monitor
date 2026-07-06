"""Compatibility shim for the canonical RSS probe strategy."""

from app.domains.sources.probe.strategies.rss import (
    KNOWN_RSS_FEEDS,
    RssProbeStrategy,
    _UNFETCHABLE,
    _USE_SCRAPING,
)

__all__ = ["KNOWN_RSS_FEEDS", "RssProbeStrategy", "_UNFETCHABLE", "_USE_SCRAPING"]
