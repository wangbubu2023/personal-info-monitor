# backend/tests/test_configs_api_auth_extended.py
"""Extended tests for configs auth API — CRUD + validation."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_auth_configs_returns_list(client: AsyncClient):
    resp = await client.get("/api/configs/auth-configs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_create_auth_config_success(client: AsyncClient):
    payload = {
        "name": "test-cfg",
        "site_url": "https://example.com",
        "auth_type": "password",
        "username": "user",
        "password": "pass",
    }
    resp = await client.post("/api/configs/auth-configs", json=payload)
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["site_url"] == "https://example.com"
    assert data["name"] == "test-cfg"


@pytest.mark.asyncio
async def test_get_auth_config_not_found(client: AsyncClient):
    resp = await client.get("/api/configs/auth-configs/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_auth_config_not_found(client: AsyncClient):
    resp = await client.delete("/api/configs/auth-configs/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_auth_config_not_found(client: AsyncClient):
    resp = await client.patch(
        "/api/configs/auth-configs/00000000-0000-0000-0000-000000000000",
        json={"name": "new-name"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_and_get_auth_config(client: AsyncClient):
    payload = {
        "name": "get-test-cfg",
        "site_url": "https://gettest.com",
        "auth_type": "password",
        "username": "admin",
        "password": "secret",
    }
    create_resp = await client.post("/api/configs/auth-configs", json=payload)
    assert create_resp.status_code in (200, 201)
    config_id = create_resp.json()["id"]

    get_resp = await client.get(f"/api/configs/auth-configs/{config_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["site_url"] == "https://gettest.com"


@pytest.mark.asyncio
async def test_create_and_delete_auth_config(client: AsyncClient):
    payload = {
        "name": "delete-me",
        "site_url": "https://deleteme.com",
        "auth_type": "password",
        "username": "user",
        "password": "pass",
    }
    create_resp = await client.post("/api/configs/auth-configs", json=payload)
    assert create_resp.status_code in (200, 201)
    config_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/api/configs/auth-configs/{config_id}")
    assert del_resp.status_code == 200
    body = del_resp.json()
    assert body.get("sources_unlinked") == 0
    assert body.get("browser_sessions_unlinked") == 0

    # Confirm it's gone
    get_resp = await client.get(f"/api/configs/auth-configs/{config_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_auth_config_unlinks_referencing_sources(client: AsyncClient):
    """Deleting an auth config must not fail when sources still reference it.

    The DELETE handler transparently unlinks referencing sources (clearing
    ``auth_required`` as well) and reports the count. Without this, the FK
    constraint would turn the action into a cryptic 500 in the UI.
    """
    auth_payload = {
        "name": "bound-cfg",
        "site_url": "https://bound.example.com",
        "auth_type": "cookie",
        "cookies": "session=abc",
    }
    auth_resp = await client.post("/api/configs/auth-configs", json=auth_payload)
    assert auth_resp.status_code in (200, 201)
    auth_id = auth_resp.json()["id"]

    src_payload = {
        "name": "bound-source",
        "type": "website",
        "url": "https://bound.example.com/news",
        "auth_required": True,
        "auth_config_id": auth_id,
    }
    src_resp = await client.post("/api/sources", json=src_payload)
    assert src_resp.status_code in (200, 201), src_resp.text
    src_id = src_resp.json()["id"]

    del_resp = await client.delete(f"/api/configs/auth-configs/{auth_id}")
    assert del_resp.status_code == 200
    body = del_resp.json()
    assert body.get("sources_unlinked") == 1

    src_get = await client.get(f"/api/sources/{src_id}")
    assert src_get.status_code == 200
    src_body = src_get.json()
    assert src_body.get("auth_config_id") in (None, "")
    assert src_body.get("auth_required") is False


@pytest.mark.asyncio
async def test_list_api_keys_returns_list(client: AsyncClient):
    resp = await client.get("/api/configs/api-keys")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_get_api_key_not_found(client: AsyncClient):
    resp = await client.get("/api/configs/api-keys/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_api_key_not_found(client: AsyncClient):
    resp = await client.delete("/api/configs/api-keys/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
