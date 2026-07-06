"""Source-probing service and strategies."""

from app.domains.sources.probe.service import (
    KNOWN_RSS_FEEDS,
    ProbeService,
    _UNFETCHABLE,
    _USE_SCRAPING,
)
from app.domains.sources.probe.strategies.registry import STRATEGY_REGISTRY
from app.domains.sources.probe.strategies.result import ProbeResult

__all__ = [
    "KNOWN_RSS_FEEDS",
    "ProbeResult",
    "ProbeService",
    "STRATEGY_REGISTRY",
    "_UNFETCHABLE",
    "_USE_SCRAPING",
]
