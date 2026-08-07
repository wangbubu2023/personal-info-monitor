"""Connector interface and permission guard."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domains.fetch.connectors.contracts import ConnectorManifest, ConnectorResult, FetchRequest
from app.models import Source


class ConnectorPermissionError(PermissionError):
    pass


class Connector(ABC):
    manifest: ConnectorManifest

    @abstractmethod
    async def fetch(self, source: Source, request: FetchRequest) -> ConnectorResult:
        raise NotImplementedError

    def assert_permission(self, permission: str) -> None:
        if permission not in self.manifest.permissions:
            raise ConnectorPermissionError(
                f"connector {self.manifest.connector_id} does not declare permission {permission}"
            )
