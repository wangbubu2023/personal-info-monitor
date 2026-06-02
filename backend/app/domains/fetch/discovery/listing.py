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

from app.domains.fetch.discovery.rules import DiscoveryRules
from app.utils.datetime import utcnow_naive


@dataclass(frozen=True)
class DiscoveredArticle:
    url: str
    title: str
    publish_time: datetime | None = None


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().lstrip("www.").rstrip(".")


def _same_domain(base_url: str, url: str) -> bool:
    base = _host(base_url)
    other = _host(url)
    if not base or not other:
        return False
    return base == other or other.endswith("." + base) or base.endswith("." + other)


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


__all__ = [
    "DiscoveredArticle",
    "filter_candidates",
]
