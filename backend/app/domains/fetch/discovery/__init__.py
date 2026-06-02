"""Controlled listing-page discovery for the website collector.

Discovery here means the *bounded* flow described in the enhancement plan §8::

    listing / section page -> recent article links -> hydrate body

It is explicitly **not** a whole-site crawler: no recursion, no URL frontier,
no robots traversal. The two modules are:

* :mod:`rules` — parse the per-source ``metadata['discovery']`` config into an
  immutable :class:`~app.domains.fetch.discovery.rules.DiscoveryRules`.
* :mod:`listing` — pure candidate filtering (same-domain, allow/deny, dedupe,
  freshness, title length) producing :class:`DiscoveredArticle` plus an
  explainable diagnostics dict.
"""

from app.domains.fetch.discovery.listing import (
    DiscoveredArticle,
    filter_candidates,
)
from app.domains.fetch.discovery.rules import DiscoveryRules, parse_discovery_rules

__all__ = [
    "DiscoveryRules",
    "parse_discovery_rules",
    "DiscoveredArticle",
    "filter_candidates",
]
