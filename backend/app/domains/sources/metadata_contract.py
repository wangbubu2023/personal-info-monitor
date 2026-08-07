"""Versioned Source metadata contract and sensitive-field quarantine."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

METADATA_SCHEMA_VERSION = "source-metadata/v1"
_SENSITIVE_KEYS = {"password", "cookie_header", "cookies", "storage_state", "access_token", "refresh_token"}


def canonicalize_source_metadata(value: dict[str, Any] | None) -> dict[str, Any]:
    metadata = deepcopy(value) if isinstance(value, dict) else {}
    metadata["schema_version"] = str(metadata.get("schema_version") or METADATA_SCHEMA_VERSION)
    if metadata["schema_version"] != METADATA_SCHEMA_VERSION:
        raise ValueError(f"unsupported source metadata schema: {metadata['schema_version']}")
    quarantine = metadata.get("quarantine") if isinstance(metadata.get("quarantine"), dict) else {}
    for key in list(metadata):
        if key.lower() in _SENSITIVE_KEYS:
            quarantine[key] = {"present": bool(metadata.pop(key)), "reason": "use AuthConfig/browser session"}
    metadata["quarantine"] = quarantine
    return metadata


def validate_source_metadata(value: dict[str, Any] | None) -> dict[str, Any]:  # noqa: V103
    metadata = canonicalize_source_metadata(value)
    if len(str(metadata)) > 1_000_000:
        raise ValueError("source metadata exceeds 1MB")
    return metadata
