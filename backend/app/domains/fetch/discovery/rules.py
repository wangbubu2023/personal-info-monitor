"""Parse per-source listing-discovery configuration into an immutable rule set.

Source authors can tune listing discovery via ``Source.metadata_['discovery']``
(plan §8.3)::

    {
      "discovery": {
        "mode": "listing",
        "listing_urls": ["https://example.com/news"],
        "max_links": 50,
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
URL) for explicit configuration. When no explicit config is present, website
sources use a conservative default rule set against the source URL itself;
empty default-discovery results fall through to the legacy static fetch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.domains.fetch.collectors.website_helpers import looks_like_article_url

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

_DEFAULT_MAX_LINKS = 50
_DEFAULT_MIN_TITLE_CHARS = 12
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
    max_links: int = 50
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
    require_article_url: bool = False
    fallback_to_static_on_empty: bool = False
    pagination_max_pages: int = 1
    pagination_param: str | None = None
    pagination_start: int = 2
    pagination_url_template: str | None = None
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
    pagination = raw.get("pagination") if isinstance(raw.get("pagination"), Mapping) else {}
    pagination_max_pages = _as_int(
        raw.get("pagination_max_pages", pagination.get("max_pages", 1)),
        1,
        lo=1,
        hi=10,
    )
    pagination_template = str(
        raw.get("pagination_url_template") or pagination.get("url_template") or ""
    ).strip() or None
    pagination_param = str(raw.get("pagination_param") or pagination.get("param") or "").strip() or None
    if pagination_max_pages > 1 and not pagination_template and not pagination_param:
        pagination_param = "page"

    return DiscoveryRules(
        mode=mode,
        listing_urls=listing_urls,
        max_links=_as_int(raw.get("max_links"), _DEFAULT_MAX_LINKS, lo=1, hi=_MAX_LINKS_CEILING),
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
        require_article_url=bool(raw.get("require_article_url", False)),
        pagination_max_pages=pagination_max_pages,
        pagination_param=pagination_param,
        pagination_start=_as_int(
            raw.get("pagination_start", pagination.get("start", 2)),
            2,
            lo=2,
            hi=100,
        ),
        pagination_url_template=pagination_template,
    )


def _explicitly_disabled(metadata: Mapping[str, Any] | None) -> bool:
    if not isinstance(metadata, Mapping):
        return False
    raw = metadata.get("discovery")
    if raw is False:
        return True
    if isinstance(raw, str) and raw.strip().lower() in {"off", "false", "disabled"}:
        return True
    if isinstance(raw, Mapping):
        mode = str(raw.get("mode") or "").strip().lower()
        return mode in {"off", "false", "disabled"}
    return metadata.get("listing_discovery") is False


def default_discovery_rules(
    source_url: str,
    metadata: Mapping[str, Any] | None = None,
) -> DiscoveryRules | None:
    """Return conservative default listing discovery rules for a website source."""
    if _explicitly_disabled(metadata):
        return None
    parsed = urlparse(str(source_url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    metadata = metadata if isinstance(metadata, Mapping) else {}
    pagination_max_pages = _as_int(
        metadata.get("discovery_default_pagination_max_pages"),
        1,
        lo=1,
        hi=10,
    )
    pagination_param_raw = str(metadata.get("discovery_default_pagination_param") or "").strip()
    pagination_param = pagination_param_raw or ("page" if pagination_max_pages > 1 else None)
    listing_urls = _as_str_tuple(metadata.get("discovery_default_listing_urls")) or (source_url,)
    return DiscoveryRules(
        mode="listing",
        listing_urls=listing_urls,
        max_links=_as_int(
            metadata.get("discovery_default_max_links"),
            _DEFAULT_MAX_LINKS,
            lo=1,
            hi=_MAX_LINKS_CEILING,
        ),
        same_domain_only=True,
        max_depth=1,
        url_deny_patterns=_DEFAULT_DENY_PATTERNS,
        min_title_chars=_as_int(
            metadata.get("discovery_default_min_title_chars"),
            _DEFAULT_MIN_TITLE_CHARS,
            lo=1,
            hi=200,
        ),
        require_article_url=True,
        fallback_to_static_on_empty=True,
        pagination_max_pages=pagination_max_pages,
        pagination_param=pagination_param,
        pagination_start=_as_int(
            metadata.get("discovery_default_pagination_start"),
            2,
            lo=2,
            hi=100,
        ),
        pagination_url_template=(
            str(metadata.get("discovery_default_pagination_url_template") or "").strip()
            or None
        ),
        extra={"default": True},
    )


def resolve_discovery_rules(
    source_url: str,
    metadata: Mapping[str, Any] | None,
) -> DiscoveryRules | None:
    """Return explicit discovery rules or the conservative default rules."""
    if _explicitly_disabled(metadata):
        return None
    explicit = parse_discovery_rules(metadata)
    if explicit is not None:
        return explicit
    return default_discovery_rules(source_url, metadata)


def candidate_satisfies_article_shape(
    base_url: str,
    url: str,
    rules: DiscoveryRules,
) -> bool:
    """Whether a candidate passes any article-shaped URL requirement."""
    if not rules.require_article_url:
        return True
    return looks_like_article_url(base_url, url)


def _page_url_with_param(url: str, param: str, page: int) -> str:
    parsed = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != param]
    query.append((param, str(page)))
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def expand_listing_urls(rules: DiscoveryRules) -> tuple[str, ...]:
    """Expand configured listing URLs into bounded same-listing pagination URLs.

    ``pagination_max_pages`` includes the first listing page. With
    ``pagination_max_pages=3`` and the default ``pagination_start=2`` this
    returns ``base``, ``?page=2`` and ``?page=3`` for each configured listing.
    """
    expanded: list[str] = []
    seen: set[str] = set()
    for listing_url in rules.listing_urls:
        for url in _expand_one_listing_url(listing_url, rules):
            if url in seen:
                continue
            seen.add(url)
            expanded.append(url)
    return tuple(expanded)


def _expand_one_listing_url(listing_url: str, rules: DiscoveryRules) -> tuple[str, ...]:
    urls = [listing_url]
    if rules.pagination_max_pages <= 1:
        return tuple(urls)
    stop = rules.pagination_start + rules.pagination_max_pages - 1
    for page in range(rules.pagination_start, stop):
        if rules.pagination_url_template:
            urls.append(
                rules.pagination_url_template.format(
                    page=page,
                    listing_url=listing_url,
                )
            )
        elif rules.pagination_param:
            urls.append(_page_url_with_param(listing_url, rules.pagination_param, page))
    return tuple(urls)


__all__ = [
    "DiscoveryRules",
    "candidate_satisfies_article_shape",
    "default_discovery_rules",
    "expand_listing_urls",
    "parse_discovery_rules",
    "resolve_discovery_rules",
]
