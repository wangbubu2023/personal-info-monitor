"""Shared numeric helpers for pim-score modules (avoids circular imports)."""

from __future__ import annotations

from typing import Any


def clamp_float(value: Any, *, default: float = 0.0, min_value: float = 0.0, max_value: float = 1.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(max_value, parsed))


def normalize_source_stars(value: Any, default: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(3, parsed))


def normalize_dimension_score(value: Any) -> float:
    return clamp_float(value, default=0.0, min_value=0.0, max_value=10.0)
