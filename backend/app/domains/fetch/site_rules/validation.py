"""Fail-closed validation and canonical hashing for site rules."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import ValidationError

from app.domains.fetch.site_rules.contracts import SiteRule, canonical_rule_document


class RuleValidationError(ValueError):
    """Raised when a rule is unsafe or outside the supported protocol."""


_DANGEROUS_TEXT = re.compile(r"(?:<\s*/?\s*script\b|javascript\s*:|data\s*:\s*text/html)", re.I)
_UNSAFE_REGEX = re.compile(r"\(\?[=!<]|\\[1-9]")


def _walk_values(value: Any, *, key: str = "") -> None:
    if isinstance(value, str):
        if len(value) > 50_000:
            raise RuleValidationError(f"rule value is too long at {key or 'root'}")
        if _DANGEROUS_TEXT.search(value):
            raise RuleValidationError(f"unsafe script or URL scheme at {key or 'root'}")
        if "regex" in key.lower() and _UNSAFE_REGEX.search(value):
            raise RuleValidationError(f"unsafe regex construct at {key}")
        return
    if isinstance(value, list):
        if len(value) > 512:
            raise RuleValidationError(f"array is too large at {key or 'root'}")
        for index, item in enumerate(value):
            _walk_values(item, key=f"{key}[{index}]")
        return
    if isinstance(value, dict):
        if len(value) > 256:
            raise RuleValidationError(f"object is too large at {key or 'root'}")
        for child_key, child_value in value.items():
            child_name = f"{key}.{child_key}" if key else str(child_key)
            _walk_values(child_value, key=child_name)


def _validate_urls(rule: SiteRule) -> None:
    if not rule.matches.hosts and not rule.matches.url_prefixes:
        raise RuleValidationError("matches must include at least one host or url_prefix")
    for host in rule.matches.hosts:
        if "://" in host or "/" in host or " " in host:
            raise RuleValidationError(f"host must be a hostname: {host!r}")
        if not re.fullmatch(r"[a-z0-9._*-]+", host):
            raise RuleValidationError(f"invalid host pattern: {host!r}")
    for prefix in rule.matches.url_prefixes:
        if not prefix.startswith("/") and not prefix.startswith("http://") and not prefix.startswith("https://"):
            raise RuleValidationError(f"url_prefix must be an absolute path or URL: {prefix!r}")


def validate_rule(payload: SiteRule | dict[str, Any]) -> SiteRule:
    """Validate a document and apply protocol safety checks."""

    try:
        rule = payload if isinstance(payload, SiteRule) else SiteRule.model_validate(payload)
    except ValidationError as exc:
        raise RuleValidationError(str(exc)) from exc
    if rule.schema_version != "site-rule/v1":
        raise RuleValidationError(f"unsupported site-rule schema: {rule.schema_version}")
    _walk_values(canonical_rule_document(rule))
    _validate_urls(rule)
    selector_count = 0
    for section in (rule.discovery, rule.identity, rule.extraction):
        selectors = section.get("selectors", []) if isinstance(section, dict) else []
        if isinstance(selectors, list):
            selector_count += len(selectors)
    if selector_count > rule.limits.max_selectors:
        raise RuleValidationError(
            f"selector count {selector_count} exceeds limit {rule.limits.max_selectors}"
        )
    encoded_size = len(json.dumps(canonical_rule_document(rule), ensure_ascii=False).encode("utf-8"))
    if encoded_size > rule.limits.max_bytes:
        raise RuleValidationError(f"rule document exceeds {rule.limits.max_bytes} bytes")
    return rule


def rule_checksum(rule: SiteRule) -> str:
    document = json.dumps(
        canonical_rule_document(validate_rule(rule)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(document).hexdigest()
