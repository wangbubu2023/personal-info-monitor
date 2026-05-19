"""Registry mapping source types to probe strategy classes.

Using a plain dict so new source types can be added without touching
:mod:`app.services.probe_service`. Each strategy class takes a single
``helpers`` argument in its constructor — see
:mod:`app.services.probe_strategies.base`.
"""

from __future__ import annotations

from typing import Dict, Type

from app.services.probe_strategies.podcast import PodcastProbeStrategy
from app.services.probe_strategies.rss import RssProbeStrategy
from app.services.probe_strategies.website import WebsiteProbeStrategy
from app.services.probe_strategies.x import XProbeStrategy
from app.services.probe_strategies.youtube import YouTubeProbeStrategy


STRATEGY_REGISTRY: Dict[str, Type] = {
    "rss": RssProbeStrategy,
    "website": WebsiteProbeStrategy,
    "x": XProbeStrategy,
    "youtube": YouTubeProbeStrategy,
    "podcast": PodcastProbeStrategy,
}
