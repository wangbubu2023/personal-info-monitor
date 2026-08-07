"""Fixture-level connector conformance checks."""

from __future__ import annotations

from typing import Any

from app.domains.fetch.connectors.contracts import ConnectorResult


def validate_connector_result(value: ConnectorResult | dict[str, Any]) -> ConnectorResult:
    result = value if isinstance(value, ConnectorResult) else ConnectorResult.model_validate(value)
    for index, item in enumerate(result.items):
        if not item.get("title") or not item.get("url"):
            raise ValueError(f"connector item {index} must contain title and url")
    return result
