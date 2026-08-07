"""Connector SDK with explicit capabilities and default-deny permissions."""

from app.domains.fetch.connectors.contracts import (
    ConnectorHealth,
    ConnectorManifest,
    ConnectorResult,
    FetchRequest,
)
from app.domains.fetch.connectors.registry import ConnectorRegistry, builtin_connectors

__all__ = [
    "ConnectorHealth",
    "ConnectorManifest",
    "ConnectorRegistry",
    "ConnectorResult",
    "FetchRequest",
    "builtin_connectors",
]
