"""Compatibility shim for the canonical sources-domain probe service."""

from app.domains.sources.probe.service import (  # noqa: F401
    KNOWN_RSS_FEEDS,
    ProbeResult,
    ProbeService,
    _UNFETCHABLE,
    _USE_SCRAPING,
    aiohttp,
    get_settings,
    settings,
)

__all__ = [
    "ProbeService",
    "ProbeResult",
    "KNOWN_RSS_FEEDS",
    "_UNFETCHABLE",
    "_USE_SCRAPING",
    "aiohttp",
    "get_settings",
    "settings",
]
