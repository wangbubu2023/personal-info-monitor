"""Event-layer scoring (momentum + corroboration) for digest clusters."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from app.domains.score.score_utils import normalize_authority_type, normalize_source_stars


def _metadata(item: Mapping[str, Any]) -> dict[str, Any]:
    meta = item.get("metadata")
    return dict(meta) if isinstance(meta, dict) else {}


def _article_score(item: Mapping[str, Any]) -> float:
    meta = _metadata(item)
    raw = item.get("article_score", item.get("final_score", meta.get("article_score", meta.get("final_score"))))
    try:
        return max(0.0, min(100.0, float(raw)))
    except (TypeError, ValueError):
        return 0.0


def _source_id(item: Mapping[str, Any]) -> str:
    sid = item.get("source_id")
    if sid:
        return str(sid).strip()
    meta = _metadata(item)
    source_meta = item.get("source_metadata")
    if isinstance(source_meta, dict) and source_meta.get("source_id"):
        return str(source_meta["source_id"]).strip()
    name = (item.get("source_name") or meta.get("source_name") or "").strip()
    return name or "unknown"


_COMMON_SECOND_LEVEL_SUFFIXES = {
    "co.uk",
    "com.au",
    "com.cn",
    "com.hk",
    "co.jp",
    "co.kr",
    "com.sg",
    "com.tw",
}


def _registrable_domain(host: str) -> str:
    labels = [part for part in host.lower().strip(".").split(".") if part]
    if len(labels) <= 2:
        return ".".join(labels)
    suffix = ".".join(labels[-2:])
    if suffix in _COMMON_SECOND_LEVEL_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return suffix


def _source_domain(item: Mapping[str, Any]) -> str:
    meta = _metadata(item)
    source_meta = item.get("source_metadata") if isinstance(item.get("source_metadata"), dict) else {}
    for raw in (
        item.get("source_url"),
        item.get("original_url"),
        item.get("url"),
        meta.get("source_url"),
        meta.get("original_url"),
        source_meta.get("url"),
        source_meta.get("source_url"),
    ):
        if not raw:
            continue
        text = str(raw)
        parsed = urlparse(text if "://" in text else f"https://{text}")
        host = parsed.hostname or ""
        if host:
            if host.startswith("www."):
                host = host[4:]
            return _registrable_domain(host)
    return ""


def _max_source_stars(items: Sequence[Mapping[str, Any]]) -> int:
    stars = []
    for item in items:
        meta = _metadata(item)
        source_meta = item.get("source_metadata") if isinstance(item.get("source_metadata"), dict) else {}
        raw = item.get("source_stars") or meta.get("source_stars") or source_meta.get("source_stars")
        stars.append(normalize_source_stars(raw))
    return max(stars) if stars else 1


def _is_official_source(item: Mapping[str, Any]) -> bool:
    source_meta = item.get("source_metadata") if isinstance(item.get("source_metadata"), dict) else {}
    meta = _metadata(item)
    auth = normalize_authority_type(
        item.get("authority_type")
        or meta.get("authority_type")
        or source_meta.get("authority_type")
        or ""
    )
    return auth in {"official", "regulator"}


def compute_momentum(items: Sequence[Mapping[str, Any]], *, now: datetime | None = None) -> float:
    size = len(items)
    if size <= 0:
        return 0.0
    now = now or datetime.utcnow()
    recent_cutoff = now - timedelta(hours=6)
    recent = 0
    for item in items:
        ts = item.get("publish_time") or item.get("fetched_at")
        if isinstance(ts, datetime) and ts >= recent_cutoff:
            recent += 1
    recent_bonus = min(2.0, recent * 0.5)
    return round(min(10.0, 2.5 * math.log2(1 + size) + recent_bonus), 2)


def compute_corroboration(items: Sequence[Mapping[str, Any]]) -> tuple[float, str, int]:
    independent_keys: set[str] = set()
    seen_duplicate_groups: set[str] = set()
    for item in items:
        meta = _metadata(item)
        duplicate_group = str(item.get("duplicate_group_id") or meta.get("duplicate_group_id") or "").strip()
        if duplicate_group:
            if duplicate_group in seen_duplicate_groups:
                continue
            seen_duplicate_groups.add(duplicate_group)
        domain = _source_domain(item)
        independent_keys.add(domain or _source_id(item))
    independent_keys.discard("unknown")
    count = len(independent_keys) if independent_keys else len(items)
    max_stars = _max_source_stars(items)
    has_official = any(_is_official_source(item) for item in items)

    if count >= 3:
        return 9.0, "strong", count
    if count == 2:
        return 6.5, "moderate", count
    if count == 1 and (max_stars >= 3 or has_official):
        return 5.5, "single_high", count
    return 2.5, "single_low", count


def compute_event_score(items: Sequence[Mapping[str, Any]], *, now: datetime | None = None) -> dict[str, Any]:
    if not items:
        return {
            "event_score": 0.0,
            "momentum": 0.0,
            "corroboration": 0.0,
            "corroboration_tier": "single_low",
            "independent_source_count": 0,
            "max_article_score": 0.0,
        }
    max_article = max(_article_score(item) for item in items)
    momentum = compute_momentum(items, now=now)
    corroboration, tier, indep = compute_corroboration(items)
    event_score = round(
        0.50 * max_article + 0.30 * momentum * 10.0 + 0.20 * corroboration * 10.0,
        2,
    )
    return {
        "event_score": min(100.0, event_score),
        "momentum": momentum,
        "corroboration": corroboration,
        "corroboration_tier": tier,
        "independent_source_count": indep,
        "max_article_score": max_article,
    }
