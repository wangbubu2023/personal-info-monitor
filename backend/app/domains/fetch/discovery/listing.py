"""Pure listing-page candidate filtering.

Given raw link candidates extracted from a listing page (each a ``dict`` with
at least ``url`` / ``title`` and optionally ``publish_time``) and a
:class:`~app.domains.fetch.discovery.rules.DiscoveryRules`, decide which become
:class:`DiscoveredArticle` rows. Every drop is counted so the result is
*explainable* — the plan (§8.6) requires being able to say "discovered N,
dropped M by deny pattern, K off-domain, …".

No network IO lives here: the collector fetches the listing HTML and extracts
candidates (reusing ``website_parser``); this module only filters. That keeps
the allow/deny/freshness logic exhaustively unit-testable from fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence
from urllib.parse import urljoin, urlparse

from app.domains.fetch.collectors import website_helpers
from app.domains.fetch.discovery.rules import DiscoveryRules, candidate_satisfies_article_shape
from app.utils.datetime import utcnow_naive

_DISCOVERY_DIAGNOSTIC_FIELDS = (
    "total",
    "kept",
    "dropped_no_url",
    "dropped_off_domain",
    "dropped_deny",
    "dropped_allow_miss",
    "dropped_non_article_url",
    "dropped_short_title",
    "dropped_duplicate",
    "dropped_stale",
    "truncated",
    "listing_urls_configured",
    "listing_pages_total",
    "listing_pages_fetched",
    "listing_pages_failed",
    "pagination_max_pages",
)


@dataclass(frozen=True)
class DiscoveredArticle:
    url: str
    title: str
    publish_time: datetime | None = None


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.").rstrip(".")


def _same_domain(base_url: str, url: str) -> bool:
    return website_helpers.same_site(base_url, url)


def _matches_any(path_and_url: str, patterns: Sequence[str]) -> bool:
    return any(pattern and pattern in path_and_url for pattern in patterns)


def _coerce_publish_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def filter_candidates(
    candidates: Sequence[Mapping[str, Any]],
    rules: DiscoveryRules,
    base_url: str,
    *,
    now: datetime | None = None,
) -> tuple[list[DiscoveredArticle], dict[str, int]]:
    """Filter raw candidates into discovered articles + a diagnostics counter."""
    now = now or utcnow_naive()
    diagnostics = {
        "total": len(candidates),
        "kept": 0,
        "dropped_no_url": 0,
        "dropped_off_domain": 0,
        "dropped_deny": 0,
        "dropped_allow_miss": 0,
        "dropped_non_article_url": 0,
        "dropped_short_title": 0,
        "dropped_duplicate": 0,
        "dropped_stale": 0,
        "truncated": 0,
    }
    kept: list[DiscoveredArticle] = []
    seen: set[str] = set()
    freshness_cutoff = (
        now - timedelta(days=rules.freshness_days) if rules.freshness_days else None
    )

    for candidate in candidates:
        raw_url = str(candidate.get("url") or "").strip()
        if not raw_url:
            diagnostics["dropped_no_url"] += 1
            continue
        url = urljoin(base_url, raw_url) if raw_url.startswith("/") else raw_url
        title = str(candidate.get("title") or "").strip()
        match_blob = url.lower()

        if rules.same_domain_only and not _same_domain(base_url, url):
            diagnostics["dropped_off_domain"] += 1
            continue
        if _matches_any(match_blob, rules.url_deny_patterns):
            diagnostics["dropped_deny"] += 1
            continue
        if rules.url_allow_patterns and not _matches_any(match_blob, rules.url_allow_patterns):
            diagnostics["dropped_allow_miss"] += 1
            continue
        if not candidate_satisfies_article_shape(base_url, url, rules):
            diagnostics["dropped_non_article_url"] += 1
            continue
        if len(title) < rules.min_title_chars:
            diagnostics["dropped_short_title"] += 1
            continue
        if url in seen:
            diagnostics["dropped_duplicate"] += 1
            continue

        publish_time = _coerce_publish_time(candidate.get("publish_time"))
        if freshness_cutoff is not None and publish_time is not None and publish_time < freshness_cutoff:
            diagnostics["dropped_stale"] += 1
            continue

        if len(kept) >= rules.max_links:
            diagnostics["truncated"] += 1
            continue

        seen.add(url)
        kept.append(DiscoveredArticle(url=url, title=title, publish_time=publish_time))

    diagnostics["kept"] = len(kept)
    return kept, diagnostics


def _as_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _write_structured_discovery_diagnostics(
    source,
    diagnostics: Mapping[str, Any],
    *,
    checked_at: datetime,
) -> None:
    if not hasattr(source, "discovery_checked_at"):
        return
    source.discovery_checked_at = checked_at
    for field in _DISCOVERY_DIAGNOSTIC_FIELDS:
        setattr(source, f"discovery_{field}", _as_int_or_none(diagnostics.get(field)))


def _structured_discovery_diagnostics(source) -> dict[str, Any]:
    checked_at = getattr(source, "discovery_checked_at", None)
    has_structured = isinstance(checked_at, datetime) or any(
        getattr(source, f"discovery_{field}", None) is not None
        for field in _DISCOVERY_DIAGNOSTIC_FIELDS
    )
    if not has_structured:
        return {}
    payload: dict[str, Any] = {}
    if isinstance(checked_at, datetime):
        payload["checked_at"] = checked_at.isoformat() + "Z"
    for field in _DISCOVERY_DIAGNOSTIC_FIELDS:
        value = getattr(source, f"discovery_{field}", None)
        if value is not None:
            payload[field] = value
    return payload


def discovery_diagnostics_metadata(source) -> dict[str, Any]:
    """Return latest discovery diagnostics, preferring structured columns."""
    structured = _structured_discovery_diagnostics(source)
    if structured:
        return structured
    metadata = getattr(source, "metadata_", None)
    if not isinstance(metadata, Mapping):
        return {}
    value = metadata.get("discovery_diagnostics")
    return dict(value) if isinstance(value, Mapping) else {}


def record_discovery_diagnostics(source, diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    """Persist latest listing-discovery diagnostics to columns and metadata."""
    checked_at = utcnow_naive()
    payload = {field: _as_int_or_none(diagnostics.get(field)) for field in _DISCOVERY_DIAGNOSTIC_FIELDS}
    payload = {key: value for key, value in payload.items() if value is not None}
    payload["checked_at"] = checked_at.isoformat() + "Z"
    _write_structured_discovery_diagnostics(source, payload, checked_at=checked_at)
    metadata = dict(getattr(source, "metadata_", None) or {})
    metadata["discovery_diagnostics"] = payload
    source.metadata_ = metadata
    return payload


__all__ = [
    "DiscoveredArticle",
    "discovery_diagnostics_metadata",
    "filter_candidates",
    "record_discovery_diagnostics",
]
