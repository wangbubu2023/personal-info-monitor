"""Stable title identity helpers for duplicate grouping."""

from __future__ import annotations

import hashlib
import re

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def _title_tokens(title: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(title or "") if token.strip()]


def _simhash(features: list[str]) -> str:
    vector = [0] * 64
    for feature in features:
        digest = int.from_bytes(hashlib.sha1(feature.encode("utf-8")).digest()[:8], "big")
        weight = max(1, min(len(feature), 8))
        for bit in range(64):
            if digest & (1 << bit):
                vector[bit] += weight
            else:
                vector[bit] -= weight
    value = 0
    for bit, score in enumerate(vector):
        if score >= 0:
            value |= 1 << bit
    return f"{value:016x}"


def title_fingerprint(title: str | None) -> str:
    """Return a stable 64-bit simhash hex string for an article title."""
    tokens = _title_tokens(title or "")
    normalized = " ".join(tokens)
    if len(normalized) < 12 or len(tokens) < 2:
        return ""

    compact = normalized.replace(" ", "")
    trigrams = [compact[idx : idx + 3] for idx in range(max(len(compact) - 2, 0))]
    features = tokens + trigrams
    return _simhash(features)


def merge_title_identity_metadata(metadata: dict | None, *, title: str | None) -> dict:
    """Stamp title fingerprint and default duplicate group metadata."""
    merged = dict(metadata or {})
    fp = title_fingerprint(title)
    if not fp:
        return merged
    merged.setdefault("title_fp", fp)
    merged.setdefault("duplicate_group_id", f"title:{fp}")
    return merged


__all__ = ["merge_title_identity_metadata", "title_fingerprint"]
