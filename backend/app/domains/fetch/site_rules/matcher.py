"""Deterministic host/path matching for site rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlsplit

from app.domains.fetch.site_rules.contracts import SiteRule, SiteRuleStatus


def _host(value: str) -> str:
    raw = str(value or "").strip().lower().rstrip(".")
    parsed = urlsplit(raw if "://" in raw else f"https://{raw}")
    return (parsed.hostname or "").lower().rstrip(".")


def _path(value: str) -> str:
    parsed = urlsplit(str(value or ""))
    return parsed.path or "/"


def _host_score(request_host: str, pattern: str) -> int:
    candidate = _host(pattern)
    if not candidate:
        return -1
    if candidate == request_host:
        return 3
    if candidate.startswith("*.") and request_host.endswith(candidate[1:]):
        return 2
    if request_host.endswith(f".{candidate}"):
        return 1
    return -1


@dataclass(frozen=True)
class RuleMatch:
    rule: SiteRule
    host_score: int
    prefix_score: int


def _compatible(rule: SiteRule, app_version: str | None) -> bool:
    if not app_version:
        return True
    minimum = rule.compatibility.min_app_version
    maximum = rule.compatibility.max_app_version
    # Versions are intentionally compared as dotted numeric tuples. Non-numeric
    # release labels are treated as incomparable and therefore fail closed.
    def parse(value: str | None) -> tuple[int, ...] | None:
        if not value:
            return None
        try:
            return tuple(int(part) for part in value.split("."))
        except ValueError:
            return None

    current = parse(app_version)
    if current is None:
        return False
    lower = parse(minimum)
    upper = parse(maximum)
    return not (lower and current < lower) and not (upper and current > upper)


def match_rules(
    url: str,
    rules: Iterable[SiteRule],
    *,
    app_version: str | None = None,
    allowed_statuses: set[SiteRuleStatus] | None = None,
) -> RuleMatch | None:
    """Return the strongest eligible match.

    Exact host beats parent host; a longer path prefix beats a shorter one;
    active/canary/shadow precedence is deterministic; revision breaks ties.
    """

    request_host = _host(url)
    request_path = _path(url)
    allowed = allowed_statuses or {
        SiteRuleStatus.ACTIVE,
        SiteRuleStatus.CANARY,
        SiteRuleStatus.SHADOW,
        SiteRuleStatus.DEGRADED,
    }
    status_score = {
        SiteRuleStatus.ACTIVE: 4,
        SiteRuleStatus.CANARY: 3,
        SiteRuleStatus.SHADOW: 2,
        SiteRuleStatus.DEGRADED: 1,
    }
    candidates: list[tuple[tuple[int, int, int, int], RuleMatch]] = []
    for rule in rules:
        if rule.status not in allowed or not _compatible(rule, app_version):
            continue
        host_scores = [_host_score(request_host, value) for value in rule.matches.hosts]
        host_score = max(host_scores, default=-1)
        if host_score < 0:
            continue
        prefixes = [value for value in rule.matches.url_prefixes if request_path.startswith(_path(value))]
        prefix_score = max((len(_path(value)) for value in prefixes), default=0)
        result = RuleMatch(rule=rule, host_score=host_score, prefix_score=prefix_score)
        candidates.append(((host_score, prefix_score, status_score[rule.status], rule.revision), result))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]
