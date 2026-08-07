"""Compile a validated rule into a bounded collector configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domains.fetch.site_rules.contracts import SiteRule
from app.domains.fetch.site_rules.validation import validate_rule


@dataclass(frozen=True)
class CompiledSiteRule:
    rule_id: str
    revision: int
    status: str
    listing_selectors: tuple[str, ...]  # noqa: V107
    article_selectors: tuple[str, ...]  # noqa: V107
    deny_patterns: tuple[str, ...]  # noqa: V107
    preferred_methods: tuple[str, ...]  # noqa: V107
    quality: dict[str, Any]


def _strings(section: dict[str, Any], key: str) -> tuple[str, ...]:
    values = section.get(key, []) if isinstance(section, dict) else []
    if not isinstance(values, list):
        return ()
    return tuple(str(value).strip() for value in values if str(value).strip())


def compile_site_rule(rule: SiteRule) -> CompiledSiteRule:
    checked = validate_rule(rule)
    discovery = checked.discovery
    extraction = checked.extraction
    identity = checked.identity
    return CompiledSiteRule(
        rule_id=checked.rule_id,
        revision=checked.revision,
        status=checked.status.value,
        listing_selectors=_strings(discovery, "selectors"),
        article_selectors=_strings(extraction, "selectors"),
        deny_patterns=_strings(identity, "deny_patterns"),
        preferred_methods=_strings(extraction, "preferred_methods") or ("readability", "jsonld"),
        quality=dict(checked.quality),
    )
