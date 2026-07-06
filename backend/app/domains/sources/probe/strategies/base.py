"""Base contract for probe strategies.

Strategies are plain classes (no mixin inheritance). They receive a
``helpers`` object whose attributes provide access to shared HTTP / feed
utilities — typically the :class:`~app.domains.sources.probe.service.ProbeService`
instance itself.

The duck-typed helpers interface is intentionally minimal so tests can
inject lightweight fakes. It must expose:

* ``async _http_get(url, timeout=...) -> Optional[str]``
* ``async _test_rss_feed(rss_url) -> ProbeResult``
* ``_check_known_feeds(url) -> Optional[str]``  (RSS strategy / website only)
* ``async _discover_rss(url) -> Optional[str]``
* ``async _try_common_rss_paths(url) -> Optional[str]``
* ``async _test_scrape(url) -> ProbeResult`` (website only)
"""

from __future__ import annotations

from typing import Protocol

from app.domains.sources.probe.strategies.result import ProbeResult


class ProbeStrategy(Protocol):
    """Strategy interface dispatched by source type."""

    async def probe(self, url: str) -> ProbeResult:  # pragma: no cover - protocol only
        ...
