from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.source import Source, SourceType


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
    assert created["saved_username"] is None
    assert created["has_password"] is False
    assert created["has_cookies"] is True
    assert created["cookie_count"] == 2

    list_response = await client.get("/api/configs/auth-configs")
    assert list_response.status_code == 200

    payload = list_response.json()
    assert len(payload) == 1
    assert payload[0]["name"] == "主 X 账号"
    assert payload[0]["is_shared"] is True
    assert payload[0]["bound_source_count"] == 0
    assert payload[0]["has_cookies"] is True


@pytest.mark.asyncio
async def test_password_auth_config_exposes_saved_username_and_password_state(client):
    create_response = await client.post(
        "/api/configs/auth-configs",
        json={
            "name": "NYTimes 登录",
            "site_url": "https://nytimes.com",
            "auth_type": "password",
            "username": "reader@example.com",
            "password": "secret-pass",
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["saved_username"] == "reader@example.com"
    assert created["has_password"] is True
    assert created["has_cookies"] is False


@pytest.mark.asyncio
async def test_shared_x_auth_config_can_bind_all_x_sources(client, db_session):
    db_session.add_all(
        [
            Source(name="X 源 A", type=SourceType.X, url="https://x.com/example_a"),
            Source(name="X 源 B", type=SourceType.X, url="https://x.com/example_b", auth_required=True),
            Source(name="网站源", type=SourceType.WEBSITE, url="https://example.com"),
        ]
    )
    await db_session.commit()

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
            "bind_all_x_sources": True,
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["bound_sources"] == 2


@pytest.mark.asyncio
async def test_shared_x_auth_config_create_defaults_bind_all_x_sources(client, db_session):
    db_session.add(
        Source(name="X 源 A", type=SourceType.X, url="https://x.com/example_a"),
    )
    await db_session.commit()

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
    assert created["bound_sources"] == 1

    result = await db_session.execute(select(Source).filter(Source.type == SourceType.X))
    x_sources = result.scalars().all()
    assert len(x_sources) == 1
    assert x_sources[0].auth_required is True
    assert str(x_sources[0].auth_config_id) == created["id"]


@pytest.mark.asyncio
async def test_shared_x_auth_config_update_can_rebind_all_x_sources(client, db_session):
    first_create = await client.post(
        "/api/configs/auth-configs",
        json={
            "name": "旧 X 账号",
            "site_url": "https://x.com",
            "auth_type": "cookie",
            "is_shared": True,
            "cookies": {
                "auth_token": "token-old",
                "ct0": "ct0-old",
            },
        },
    )
    assert first_create.status_code == 200
    old_config_id = first_create.json()["id"]

    db_session.add_all(
        [
            Source(
                name="X 源 A",
                type=SourceType.X,
                url="https://x.com/example_a",
                auth_required=True,
                auth_config_id=old_config_id,
            ),
            Source(
                name="X 源 B",
                type=SourceType.X,
                url="https://x.com/example_b",
            ),
        ]
    )
    await db_session.commit()

    update_response = await client.patch(
        f"/api/configs/auth-configs/{old_config_id}",
        json={
            "name": "新 X 账号",
            "bind_all_x_sources": True,
        },
    )

    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["bound_sources"] == 1

    result = await db_session.execute(select(Source).order_by(Source.name))
    x_sources = result.scalars().all()
    assert all(source.auth_required is True for source in x_sources)
    assert all(source.auth_config_id == old_config_id for source in x_sources)
