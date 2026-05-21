"""Schema version constants for the normalized atoms layer."""

from __future__ import annotations

CURRENT_SCHEMA_VERSION: int = 2

SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({2})


__all__ = ["CURRENT_SCHEMA_VERSION", "SUPPORTED_SCHEMA_VERSIONS"]
