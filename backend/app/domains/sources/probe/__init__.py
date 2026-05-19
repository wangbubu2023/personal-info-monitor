"""Source-probing service and strategies.

This package is the new canonical location for the source-type probing
logic. New application code MUST import from here, e.g.::

    from app.domains.sources.probe import ProbeService, ProbeResult

The original modules ``app.services.probe_service`` and
``app.services.probe_strategies.*`` remain in place as **re-export
facades** so that the existing test suite (which patches private symbols
like ``app.services.probe_service.aiohttp.ClientSession``) keeps
working. Phase 7 of the refactor will:

1. Move the implementation files into ``app.domains.sources.probe`` and
   ``app.domains.sources.probe.strategies``.
2. Rewrite the affected ``unittest.mock.patch`` targets in one sweep.
3. Delete the legacy ``app.services.probe_*`` re-export shims.

Until then, importing from this package is equivalent to importing from
``app.services.probe_service`` — just with the correct domain home.
"""

from app.services.probe_service import ProbeService  # noqa: F401 — re-export
from app.services.probe_strategies.registry import (  # noqa: F401 — re-export
    STRATEGY_REGISTRY,
)
from app.services.probe_strategies.result import (  # noqa: F401 — re-export
    ProbeResult,
)

__all__ = [
    "ProbeResult",
    "ProbeService",
    "STRATEGY_REGISTRY",
]
