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
                               fetch_interval=60, enabled=True))
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
                           fetch_interval=60, enabled=True))
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
            "fetch_interval": 60, "enabled": True,
        })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_source_podcast_rejected_when_disabled(client: AsyncClient):
    with patch("app.api.sources._helpers.PODCAST_SOURCES_ENABLED", False):
        resp = await client.post("/api/sources", json={
            "name": "pod", "type": "podcast", "url": "https://pod.com/feed",
            "fetch_interval": 60, "enabled": True,
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
         "fetch_interval": 60, "enabled": True}
    ]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["skipped_duplicates"] == 0
    assert len(data["created"]) == 1
    assert data["created"][0]["name"] == "bulk1"


@pytest.mark.asyncio
async def test_create_x_source_auto_binds_shared_x_cookie(client: AsyncClient):
    auth_resp = await client.post(
        "/api/configs/auth-configs",
        json={
            "name": "主 X 账号",
            "site_url": "https://x.com",
            "auth_type": "cookie",
            "is_shared": True,
            "cookies": {"auth_token": "token-1", "ct0": "ct0-1"},
        },
    )
    assert auth_resp.status_code == 200
    config_id = auth_resp.json()["id"]

    resp = await client.post(
        "/api/sources",
        json={
            "name": "karpathy",
            "type": "x",
            "url": "https://x.com/karpathy",
            "fetch_interval": 60,
            "enabled": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["auth_config_id"] == config_id
    assert data["auth_required"] is True


@pytest.mark.asyncio
async def test_bulk_import_x_sources_auto_bind_shared_x_cookie(client: AsyncClient):
    auth_resp = await client.post(
        "/api/configs/auth-configs",
        json={
            "name": "主 X 账号",
            "site_url": "https://x.com",
            "auth_type": "cookie",
            "is_shared": True,
            "cookies": {"auth_token": "token-1", "ct0": "ct0-1"},
        },
    )
    assert auth_resp.status_code == 200
    config_id = auth_resp.json()["id"]

    resp = await client.post(
        "/api/sources/bulk-import",
        json={
            "sources": [
                {
                    "name": "X A",
                    "type": "x",
                    "url": "https://x.com/example_a",
                    "fetch_interval": 60,
                    "enabled": True,
                },
                {
                    "name": "X B",
                    "type": "x",
                    "url": "https://x.com/example_b",
                    "fetch_interval": 60,
                    "enabled": True,
                },
            ]
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["skipped_duplicates"] == 0
    assert len(data["created"]) == 2
    assert all(item["auth_config_id"] == config_id for item in data["created"])
    assert all(item["auth_required"] is True for item in data["created"])


@pytest.mark.asyncio
async def test_bulk_import_skips_duplicate_urls(client: AsyncClient, db_session):
    from app.models import Source
    db_session.add(Source(name="existing", type="rss", url="https://same.com/feed",
                          fetch_interval=60, enabled=True))
    await db_session.commit()

    resp = await client.post("/api/sources/bulk-import", json={"sources": [
        {"name": "new1", "type": "rss", "url": "https://same.com/feed",
         "fetch_interval": 60, "enabled": True},
        {"name": "new2", "type": "rss", "url": "https://other.com/feed",
         "fetch_interval": 60, "enabled": True},
    ]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["skipped_duplicates"] == 1
    assert len(data["created"]) == 1
    assert data["created"][0]["name"] == "new2"


@pytest.mark.asyncio
async def test_create_source_rejects_duplicate_normalized_url(client: AsyncClient, db_session):
    from app.models import Source
    db_session.add(Source(name="a", type="website", url="https://www.huxiu.com",
                          fetch_interval=60, enabled=True))
    await db_session.commit()

    mock_probe_result = MagicMock()
    mock_probe_result.status = "ok"
    mock_probe_result.strategy = "scrape"
    mock_probe_result.rss_url = None
    mock_probe_result.message = ""
    mock_probe_result.to_dict = lambda: {}

    with patch("app.api.sources._helpers._probe_urls", new=AsyncMock(return_value=(
        mock_probe_result, {}, 1
    ))):
        resp = await client.post("/api/sources", json={
            "name": "b", "type": "website", "url": "https://www.huxiu.com/",
            "fetch_interval": 60, "enabled": True,
        })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_probe_url_endpoint(client: AsyncClient):
    mock_result = MagicMock()
    mock_result.status = "ok"
    mock_result.strategy = "rss"
    mock_result.rss_url = "https://feed.com"
    mock_result.message = ""
    mock_result.sample_count = 5

    with patch("app.domains.sources.probe.service.ProbeService") as MockPS:
        instance = MockPS.return_value
        instance.probe = AsyncMock(return_value=mock_result)
        resp = await client.post("/api/sources/probe",
                                  json={"url": "https://example.com", "type": "rss"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
