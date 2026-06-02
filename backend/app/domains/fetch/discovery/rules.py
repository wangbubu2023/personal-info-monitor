"""Parse per-source listing-discovery configuration into an immutable rule set.

Source authors opt in via ``Source.metadata_['discovery']`` (plan §8.3)::

    {
      "discovery": {
        "mode": "listing",
        "listing_urls": ["https://example.com/news"],
        "max_links": 20,
        "same_domain_only": true,
        "max_depth": 1,
        "url_allow_patterns": ["/news/", "/article/"],
        "url_deny_patterns": ["/login", "/tag/"],
        "article_selector": "article",
        "title_selector": "h2 a",
        "link_selector": "a",
        "date_selector": "time",
        "min_title_chars": 8,
        "freshness_days": 7
      }
    }

Everything is optional except an enabling ``mode`` (and at least one listing
URL); sensible defaults — including a conservative deny list for
login/tag/author/search pages — are filled in here so the collector and the
pure filtering logic never have to special-case missing config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

_DEFAULT_DENY_PATTERNS = (
    "/login",
    "/signin",
    "/sign-in",
    "/register",
    "/subscribe",
    "/account",
    "/privacy",
    "/terms",
    "/tag/",
    "/tags/",
    "/author/",
    "/authors/",
    "/search",
    "/category/",
)

_MAX_LINKS_CEILING = 50


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return ()
    out: list[str] = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return tuple(out)


def _as_int(value: Any, default: int, *, lo: int, hi: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, parsed))


@dataclass(frozen=True)
class DiscoveryRules:
    mode: str
    listing_urls: tuple[str, ...]
    max_links: int = 20
    same_domain_only: bool = True
    max_depth: int = 1
    url_allow_patterns: tuple[str, ...] = ()
    url_deny_patterns: tuple[str, ...] = _DEFAULT_DENY_PATTERNS
    article_selector: str | None = None
    title_selector: str | None = None
    link_selector: str | None = None
    date_selector: str | None = None
    min_title_chars: int = 8
    freshness_days: int | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        return self.mode == "listing" and bool(self.listing_urls)


def parse_discovery_rules(metadata: Mapping[str, Any] | None) -> DiscoveryRules | None:
    """Return :class:`DiscoveryRules` when discovery is configured, else ``None``."""
    if not isinstance(metadata, Mapping):
        return None
    raw = metadata.get("discovery")
    if not isinstance(raw, Mapping):
        return None

    mode = str(raw.get("mode") or "").strip().lower()
    if mode not in ("listing",):
        return None

    listing_urls = _as_str_tuple(raw.get("listing_urls"))
    if not listing_urls:
        return None

    deny = _as_str_tuple(raw.get("url_deny_patterns")) or _DEFAULT_DENY_PATTERNS

    return DiscoveryRules(
        mode=mode,
        listing_urls=listing_urls,
        max_links=_as_int(raw.get("max_links"), 20, lo=1, hi=_MAX_LINKS_CEILING),
        same_domain_only=bool(raw.get("same_domain_only", True)),
        max_depth=_as_int(raw.get("max_depth"), 1, lo=1, hi=1),  # hard-capped: no recursion
        url_allow_patterns=_as_str_tuple(raw.get("url_allow_patterns")),
        url_deny_patterns=deny,
        article_selector=(str(raw["article_selector"]).strip() if raw.get("article_selector") else None),
        title_selector=(str(raw["title_selector"]).strip() if raw.get("title_selector") else None),
        link_selector=(str(raw["link_selector"]).strip() if raw.get("link_selector") else None),
        date_selector=(str(raw["date_selector"]).strip() if raw.get("date_selector") else None),
        min_title_chars=_as_int(raw.get("min_title_chars"), 8, lo=1, hi=200),
        freshness_days=(
            _as_int(raw.get("freshness_days"), 7, lo=1, hi=365)
            if raw.get("freshness_days") is not None
            else None
        ),
    )


__all__ = [
    "DiscoveryRules",
    "parse_discovery_rules",
]
