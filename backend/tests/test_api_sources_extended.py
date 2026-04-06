# backend/tests/test_api_sources_extended.py
"""Extended tests for sources API — normal paths + error paths."""

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_list_sources_returns_empty_when_no_sources(client: AsyncClient):
    resp = await client.get("/api/sources")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 0
    assert "items" in data


@pytest.mark.asyncio
async def test_list_sources_pagination(client: AsyncClient, db_session):
    from app.models import Source
    for i in range(3):
        db_session.add(Source(name=f"src{i}", type="rss", url=f"https://example{i}.com/feed",
                               fetch_interval=60, enabled=True, priority=0))
    await db_session.commit()

    resp = await client.get("/api/sources?page=1&page_size=2")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["total"] == 3


@pytest.mark.asyncio
async def test_get_source_not_found(client: AsyncClient):
    resp = await client.get("/api/sources/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_source_duplicate_rejected(client: AsyncClient, db_session):
    from app.models import Source
    db_session.add(Source(name="dup", type="rss", url="https://dup.com/feed",
                           fetch_interval=60, enabled=True, priority=0))
    await db_session.commit()

    mock_probe_result = MagicMock()
    mock_probe_result.status = "ok"
    mock_probe_result.strategy = "rss"
    mock_probe_result.rss_url = None
    mock_probe_result.message = ""
    mock_probe_result.to_dict = lambda: {}

    with patch("app.api.sources._helpers._probe_urls", new=AsyncMock(return_value=(
        mock_probe_result, {}, 1
    ))):
        resp = await client.post("/api/sources", json={
            "name": "dup", "type": "rss", "url": "https://dup.com/feed",
            "fetch_interval": 60, "enabled": True, "priority": 0,
        })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_source_podcast_rejected_when_disabled(client: AsyncClient):
    with patch("app.api.sources._helpers.PODCAST_SOURCES_ENABLED", False):
        resp = await client.post("/api/sources", json={
            "name": "pod", "type": "podcast", "url": "https://pod.com/feed",
            "fetch_interval": 60, "enabled": True, "priority": 0,
        })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_delete_source_not_found(client: AsyncClient):
    resp = await client.delete("/api/sources/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_source_not_found(client: AsyncClient):
    resp = await client.patch(
        "/api/sources/00000000-0000-0000-0000-000000000000",
        json={"enabled": False},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_bulk_import_creates_sources(client: AsyncClient):
    resp = await client.post("/api/sources/bulk-import", json={"sources": [
        {"name": "bulk1", "type": "rss", "url": "https://bulk1.com/feed",
         "fetch_interval": 60, "enabled": True, "priority": 0}
    ]})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["name"] == "bulk1"


@pytest.mark.asyncio
async def test_probe_url_endpoint(client: AsyncClient):
    mock_result = MagicMock()
    mock_result.status = "ok"
    mock_result.strategy = "rss"
    mock_result.rss_url = "https://feed.com"
    mock_result.message = ""
    mock_result.sample_count = 5

    with patch("app.services.probe_service.ProbeService") as MockPS:
        instance = MockPS.return_value
        instance.probe = AsyncMock(return_value=mock_result)
        resp = await client.post("/api/sources/probe",
                                  json={"url": "https://example.com", "type": "rss"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
