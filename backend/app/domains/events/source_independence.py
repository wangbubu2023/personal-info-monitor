"""PSL-backed source independence and canonical report selection."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable
from urllib.parse import urlparse

from publicsuffix2 import get_sld

from app.domains.events.config import event_config

PSL_VERSION = "publicsuffix2-20191221"


def registrable_domain(url: str | None) -> str:
    raw = str(url or "").strip()
    if not raw:
        return "unknown"
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower().strip(".")
    if not host:
        return "unknown"
    return str(get_sld(host, strict=False) or host)


def source_role(item: Any) -> str:
    metadata = getattr(item, "metadata_", None)
    if not isinstance(metadata, dict) and isinstance(item, dict):
        metadata = item.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    explicit = str(metadata.get("source_role") or "").strip().lower()
    if explicit in event_config().source_weights:
        return explicit
    source = getattr(item, "source", None)
    source_name = str(getattr(source, "name", "") or "").lower()
    source_url = str(getattr(source, "url", "") or "")
    if isinstance(item, dict):
        source_name = str(item.get("source_name") or source_name).lower()
        source_url = str(item.get("source_url") or source_url)
    if any(marker in source_name for marker in ("government", "regulator", "official", "政府", "监管", "官方")):
        return "official"
    if metadata.get("is_reprint") or metadata.get("syndicated_from"):
        return "reprint"
    if any(marker in source_name for marker in ("reuters", "associated press", "afp", "新华社")):
        return "wire"
    if any(marker in source_name for marker in ("aggregator", "聚合")):
        return "aggregator"
    if source_url:
        return "original"
    return "unknown"


def origin_group(item: Any) -> str:
    metadata = getattr(item, "metadata_", None)
    if not isinstance(metadata, dict) and isinstance(item, dict):
        metadata = item.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    explicit = str(
        metadata.get("origin_group")
        or metadata.get("syndication_group")
        or metadata.get("ownership_group")
        or ""
    ).strip()
    if explicit:
        return explicit
    source = getattr(item, "source", None)
    url = getattr(item, "original_url", None) or getattr(source, "url", None)
    if isinstance(item, dict):
        url = item.get("article_url") or item.get("url") or item.get("source_url") or url
    return registrable_domain(str(url or ""))


def independence_summary(items: Iterable[Any]) -> dict[str, Any]:
    material = list(items)
    domains: set[str] = set()
    groups: dict[str, list[tuple[str, float]]] = defaultdict(list)
    weights = event_config().source_weights
    roles: dict[str, int] = defaultdict(int)
    for item in material:
        group = origin_group(item)
        role = source_role(item)
        roles[role] += 1
        groups[group].append((role, float(weights.get(role, weights["unknown"]))))
        source = getattr(item, "source", None)
        url = getattr(item, "original_url", None) or getattr(source, "url", None)
        if isinstance(item, dict):
            url = item.get("article_url") or item.get("url") or item.get("source_url") or url
        domains.add(registrable_domain(str(url or "")))
    effective_weight = 0.0
    for rows in groups.values():
        # A wire/ownership/syndication group contributes at most one full
        # confirmation regardless of how many reprints it contains.
        effective_weight += min(1.0, max((weight for _, weight in rows), default=0.0))
    return {
        "material_count": len(material),
        "registrable_domain_count": len(domains - {"unknown"}),
        "effective_independent_source_count": int(effective_weight),
        "effective_independent_source_weight": round(effective_weight, 3),
        "origin_group_count": len(groups),
        "source_roles": dict(sorted(roles.items())),
        "psl_version": PSL_VERSION,
    }


def canonical_report(items: Iterable[Any]) -> tuple[Any | None, dict[str, Any]]:
    material = list(items)
    if not material:
        return None, {"reason": "no_material"}
    role_priority = {"official": 7, "original": 6, "wire": 5, "commentary": 3, "unknown": 2, "reprint": 1, "aggregator": 0}

    def score(item: Any) -> tuple[float, str]:
        role = source_role(item)
        full = str(getattr(item, "full_content", "") or (item.get("full_content") if isinstance(item, dict) else ""))
        summary = str(getattr(item, "summary", "") or (item.get("summary") if isinstance(item, dict) else ""))
        accessibility = 0 if (getattr(item, "metadata_", {}) or {}).get("paywalled") else 1
        value = role_priority.get(role, 2) * 10 + min(20, len(full) / 500) + min(5, len(summary) / 100) + accessibility
        return value, str(getattr(item, "id", "") or (item.get("content_id") if isinstance(item, dict) else ""))

    selected = max(material, key=score)
    role = source_role(selected)
    return selected, {
        "reason": "source_role_body_quality_accessibility",
        "source_role": role,
        "score": round(score(selected)[0], 3),
        "origin_group": origin_group(selected),
        "psl_version": PSL_VERSION,
    }


__all__ = [
    "PSL_VERSION",
    "canonical_report",
    "independence_summary",
    "origin_group",
    "registrable_domain",
    "source_role",
]
