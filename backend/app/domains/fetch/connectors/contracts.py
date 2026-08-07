"""Versioned connector manifest and transport contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConnectorManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)  # noqa: V107

    schema_version: str = "connector/v1"
    connector_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,63}$")
    version: str = Field(min_length=1, max_length=32)
    source_types: list[str] = Field(min_length=1, max_length=16)
    capabilities: list[str] = Field(default_factory=list, max_length=32)
    permissions: list[str] = Field(default_factory=list, max_length=16)
    auth_modes: list[str] = Field(default_factory=list, max_length=16)  # noqa: V107


class FetchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # noqa: V107

    source_id: str
    url: str
    limit: int = Field(default=20, ge=1, le=100)
    trace_id: str | None = None


class ConnectorResult(BaseModel):
    model_config = ConfigDict(extra="forbid")  # noqa: V107

    items: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    storage_result: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    trace_id: str | None = None


class ConnectorHealth(BaseModel):
    connector_id: str
    status: str
    latency_ms: int | None = None
    error_code: str | None = None  # noqa: V107
    checked_at: str
