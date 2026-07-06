"""Registry mapping source types to probe strategy classes.

Using a plain dict so new source types can be added without touching
:mod:`app.domains.sources.probe.service`. Each strategy class takes a single
``helpers`` argument in its constructor — see
:mod:`app.domains.sources.probe.strategies.base`.
"""

from __future__ import annotations

from typing import Dict, Type

from app.domains.sources.probe.strategies.podcast import PodcastProbeStrategy
from app.domains.sources.probe.strategies.rss import RssProbeStrategy
from app.domains.sources.probe.strategies.website import WebsiteProbeStrategy
from app.domains.sources.probe.strategies.x import XProbeStrategy
from app.domains.sources.probe.strategies.youtube import YouTubeProbeStrategy


STRATEGY_REGISTRY: Dict[str, Type] = {
    "rss": RssProbeStrategy,
    "website": WebsiteProbeStrategy,
    "x": XProbeStrategy,
    "youtube": YouTubeProbeStrategy,
    "podcast": PodcastProbeStrategy,
}
