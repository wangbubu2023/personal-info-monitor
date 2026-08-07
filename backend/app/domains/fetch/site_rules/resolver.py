"""Resolve source metadata or URL to one site-rule revision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domains.fetch.site_rules.contracts import SiteRule
from app.domains.fetch.site_rules.matcher import RuleMatch, match_rules
from app.domains.fetch.site_rules.registry import RuleRegistry, builtin_registry


@dataclass(frozen=True)
class ResolvedSiteRule:
    rule: SiteRule | None
    mode: str
    reason: str

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule.rule_id if self.rule else None,
            "revision": self.rule.revision if self.rule else None,
            "status": self.rule.status.value if self.rule else None,
            "mode": self.mode,
            "reason": self.reason,
        }


def resolve_site_rule(
    url: str,
    source_metadata: dict[str, Any] | None = None,
    *,
    registry: RuleRegistry | None = None,
    app_version: str | None = None,
) -> ResolvedSiteRule:
    rules = registry or builtin_registry
    metadata = source_metadata if isinstance(source_metadata, dict) else {}
    configured = metadata.get("site_rule") if isinstance(metadata.get("site_rule"), dict) else {}
    configured_id = str(configured.get("rule_id") or "").strip()
    if configured_id:
        revision = configured.get("revision")
        try:
            configured_rule = rules.get(configured_id, int(revision) if revision is not None else None)
        except (TypeError, ValueError):
            configured_rule = None
        if configured_rule is None:
            return ResolvedSiteRule(None, "unmatched", f"configured rule not found: {configured_id}/{revision}")
        return ResolvedSiteRule(configured_rule, configured_rule.status.value, "source metadata binding")

    match: RuleMatch | None = match_rules(url, rules.eligible(), app_version=app_version)
    if match is None:
        return ResolvedSiteRule(None, "unmatched", "no eligible site rule matched")
    return ResolvedSiteRule(match.rule, match.rule.status.value, "host/path registry match")
