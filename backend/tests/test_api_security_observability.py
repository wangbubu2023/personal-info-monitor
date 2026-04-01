from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app import auth
from app.main import app


def test_verify_api_key_rejects_missing_server_configuration(monkeypatch):
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(pim_api_key=""))

    with pytest.raises(HTTPException) as exc_info:
        auth.verify_api_key("anything")

    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_livez_is_public_and_health_requires_api_key():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        livez = await client.get("/livez")
        assert livez.status_code == 200
        assert livez.json()["status"] == "ok"

        health = await client.get("/health")
        assert health.status_code == 401


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_request_counters(client):
    await client.get("/api/categories")

    response = await client.get("/api/system/metrics")
    assert response.status_code == 200
    payload = response.json()

    assert payload["http"]["total_requests"] >= 1
    assert payload["http"]["top_routes"]["GET /api/categories"] >= 1
    assert "scheduler" in payload
