"""Reference RSS connector built on the existing RSS collector."""

from __future__ import annotations

from app.domains.fetch.collectors.rss import RSSCollector
from app.domains.fetch.connectors.base import Connector
from app.domains.fetch.connectors.conformance import validate_connector_result
from app.domains.fetch.connectors.contracts import ConnectorManifest, ConnectorResult, FetchRequest
from app.models import Source


class ReferenceRSSConnector(Connector):
    manifest = ConnectorManifest(
        connector_id="reference.rss",
        version="1.0.0",
        source_types=["rss"],
        capabilities=["discover", "fetch", "normalize", "health"],
        permissions=["network.public_http"],
        auth_modes=["none"],
    )

    def __init__(self):
        self.collector = RSSCollector()

    async def fetch(self, source: Source, request: FetchRequest) -> ConnectorResult:
        self.assert_permission("network.public_http")
        items = await self.collector.fetch(source)
        return validate_connector_result(ConnectorResult(items=items[: request.limit], trace_id=request.trace_id))
