"""Versioned, fail-closed site-rule runtime.

Site rules are deliberately kept separate from collectors.  The registry and
resolver decide *which* rule is eligible; the compiler exposes a bounded,
side-effect-free configuration to a collector.  A source without a matching
rule continues through the existing generic collector and is explicitly
reported as ``unmatched``.
"""

from app.domains.fetch.site_rules.compiler import CompiledSiteRule, compile_site_rule
from app.domains.fetch.site_rules.contracts import SiteRule, SiteRuleStatus
from app.domains.fetch.site_rules.diagnostics import RuleDiagnostics, RuleHealth
from app.domains.fetch.site_rules.matcher import RuleMatch, match_rules
from app.domains.fetch.site_rules.registry import RuleRegistry, builtin_registry
from app.domains.fetch.site_rules.resolver import ResolvedSiteRule, resolve_site_rule
from app.domains.fetch.site_rules.validation import RuleValidationError, validate_rule

__all__ = [
    "CompiledSiteRule",
    "ResolvedSiteRule",
    "RuleDiagnostics",
    "RuleHealth",
    "RuleMatch",
    "RuleRegistry",
    "RuleValidationError",
    "SiteRule",
    "SiteRuleStatus",
    "builtin_registry",
    "compile_site_rule",
    "match_rules",
    "resolve_site_rule",
    "validate_rule",
]
