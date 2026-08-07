"""Pydantic contracts for the versioned site-rule protocol."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SiteRuleStatus(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"  # noqa: V107
    SHADOW = "shadow"
    CANARY = "canary"
    ACTIVE = "active"
    DEGRADED = "degraded"
    RETIRED = "retired"


class RuleMatchContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)  # noqa: V107

    hosts: list[str] = Field(default_factory=list, max_length=64)
    url_prefixes: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("hosts", "url_prefixes")  # noqa: V105
    @classmethod
    def _clean_values(cls, values: list[str]) -> list[str]:  # noqa: V105
        result: list[str] = []
        for raw in values:
            value = str(raw).strip().lower().rstrip(".")
            if value and value not in result:
                result.append(value)
        return result


class RuleCompatibility(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)  # noqa: V107

    min_app_version: str | None = None
    max_app_version: str | None = None


class RuleLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")  # noqa: V107

    max_bytes: int = Field(default=512_000, ge=1, le=5_000_000)
    max_string: int = Field(default=2_000, ge=1, le=50_000)  # noqa: V107
    max_arrays: int = Field(default=64, ge=1, le=512)  # noqa: V107
    max_selectors: int = Field(default=64, ge=1, le=256)
    max_output: int = Field(default=1_000_000, ge=1, le=10_000_000)  # noqa: V107


class SiteRule(BaseModel):
    """The public site-rule document.

    ``extra='forbid'`` is the fail-closed boundary for future protocol fields:
    an operator must upgrade the validator before an unknown capability can be
    accepted.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)  # noqa: V107

    schema_version: str = Field(default="site-rule/v1", min_length=1, max_length=32)
    rule_id: str = Field(min_length=1, max_length=96, pattern=r"^[a-z0-9][a-z0-9_.-]{0,95}$")
    revision: int = Field(ge=1, le=1_000_000)
    status: SiteRuleStatus = SiteRuleStatus.DRAFT
    owner: str = Field(default="platform", min_length=1, max_length=128)
    description: str = Field(default="", max_length=2_000)
    matches: RuleMatchContract
    compatibility: RuleCompatibility = Field(default_factory=RuleCompatibility)
    discovery: dict[str, Any] = Field(default_factory=dict)
    identity: dict[str, Any] = Field(default_factory=dict)
    hydration: dict[str, Any] = Field(default_factory=dict)  # noqa: V107
    extraction: dict[str, Any] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    fallback: dict[str, Any] = Field(default_factory=dict)
    fixtures: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    limits: RuleLimits = Field(default_factory=RuleLimits)


def canonical_rule_document(rule: SiteRule) -> dict[str, Any]:
    """Return a deterministic JSON-compatible representation."""

    return rule.model_dump(mode="json", exclude_none=True)
