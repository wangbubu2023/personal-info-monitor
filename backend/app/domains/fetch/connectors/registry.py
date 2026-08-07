"""Static connector registry with manifest compatibility checks."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from app.domains.fetch.connectors.base import Connector
from app.domains.fetch.connectors.contracts import ConnectorHealth
from app.domains.fetch.connectors.rss import ReferenceRSSConnector


class ConnectorRegistry:
    def __init__(self, connectors: Iterable[Connector] | None = None):
        self._connectors: dict[str, Connector] = {}
        for connector in connectors or ():
            self.register(connector)

    def register(self, connector: Connector) -> None:
        manifest = connector.manifest
        if manifest.schema_version != "connector/v1":
            raise ValueError(f"unsupported connector manifest: {manifest.schema_version}")
        if manifest.connector_id in self._connectors:
            raise ValueError(f"duplicate connector: {manifest.connector_id}")
        self._connectors[manifest.connector_id] = connector

    def get(self, connector_id: str) -> Connector | None:
        return self._connectors.get(str(connector_id).strip())

    def list_manifests(self):
        return [connector.manifest for connector in sorted(self._connectors.values(), key=lambda item: item.manifest.connector_id)]

    def health(self) -> list[ConnectorHealth]:
        timestamp = datetime.now(timezone.utc).isoformat()
        return [
            ConnectorHealth(connector_id=manifest.connector_id, status="registered", checked_at=timestamp)
            for manifest in self.list_manifests()
        ]


builtin_connectors = ConnectorRegistry([ReferenceRSSConnector()])
