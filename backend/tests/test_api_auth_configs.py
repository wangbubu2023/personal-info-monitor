from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_shared_x_auth_config_round_trip(client):
    create_response = await client.post(
        "/api/configs/auth-configs",
        json={
            "name": "主 X 账号",
            "site_url": "https://x.com",
            "auth_type": "cookie",
            "is_shared": True,
            "cookies": {
                "auth_token": "token-1",
                "ct0": "ct0-1",
            },
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["name"] == "主 X 账号"
    assert created["is_shared"] is True
    assert created["bound_source_count"] == 0
    assert created["has_credentials"] is True

    list_response = await client.get("/api/configs/auth-configs")
    assert list_response.status_code == 200

    payload = list_response.json()
    assert len(payload) == 1
    assert payload[0]["name"] == "主 X 账号"
    assert payload[0]["is_shared"] is True
    assert payload[0]["bound_source_count"] == 0
