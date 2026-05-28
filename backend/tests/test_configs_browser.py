"""Tests for app.api.configs_browser — browser session management API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.configs_browser import HeadfulBrowserUnavailableError, _browser_error_message
from app.auth import verify_api_key
from app.database import Base, get_async_db
from app.main import app
from app.models.browser_session import BrowserSession, BrowserSessionStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def _db_factory(tmp_path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    db_path = tmp_path / "test_browser.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(_db_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncClient]:
    async def override_get_async_db() -> AsyncIterator[AsyncSession]:
        async with _db_factory() as session:
            yield session

    app.dependency_overrides[get_async_db] = override_get_async_db
    app.dependency_overrides[verify_api_key] = lambda: "test-api-key"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# _browser_error_message
# ---------------------------------------------------------------------------

class TestBrowserErrorMessage:

    def test_formats_action(self):
        msg = _browser_error_message("浏览器会话启动")
        assert "浏览器会话启动" in msg
        assert "失败" in msg


# ---------------------------------------------------------------------------
# GET /browser-sessions (list)
# ---------------------------------------------------------------------------

class TestListBrowserSessions:

    @pytest.mark.asyncio
    async def test_empty_list(self, client: AsyncClient):
        with patch("app.api.configs_browser.serialize_browser_session", side_effect=lambda s: {"id": str(s.id)}):
            resp = await client.get("/api/configs/browser-sessions")
            assert resp.status_code == 200
            assert resp.json() == []


# ---------------------------------------------------------------------------
# POST /browser-sessions (create)
# ---------------------------------------------------------------------------

class TestCreateBrowserSession:

    @pytest.mark.asyncio
    async def test_invalid_site_url(self, client: AsyncClient):
        resp = await client.post("/api/configs/browser-sessions", json={"site_url": ""})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_new_session(self, client: AsyncClient, tmp_path):
        with patch("app.api.configs_browser.profiles_root", return_value=tmp_path):
            with patch("app.api.configs_browser.slugify_profile_name", return_value="example-com"):
                with patch("app.api.configs_browser.serialize_browser_session") as mock_serialize:
                    mock_serialize.return_value = {
                        "id": "some-id",
                        "site_host": "example.com",
                        "status": "needs_login",
                    }
                    with patch("app.api.configs_browser.bind_browser_session_to_sources", new_callable=AsyncMock, return_value=0):
                        resp = await client.post(
                            "/api/configs/browser-sessions",
                            json={"site_url": "https://example.com"},
                        )
                        assert resp.status_code == 200
                        data = resp.json()
                        assert data["site_host"] == "example.com"
                        assert data["bound_sources"] == 0

    @pytest.mark.asyncio
    async def test_create_session_upserts_existing(self, client: AsyncClient, tmp_path, _db_factory):
        async with _db_factory() as db:
            session = BrowserSession(
                site_url="https://example.com",
                site_host="example.com",
                profile_name="example-com",
                user_data_dir=str(tmp_path / "example-com"),
                storage_state_path=str(tmp_path / "example-com" / "storage_state.json"),
                status=BrowserSessionStatus.NEEDS_LOGIN,
            )
            db.add(session)
            await db.commit()

        with patch("app.api.configs_browser.profiles_root", return_value=tmp_path):
            with patch("app.api.configs_browser.slugify_profile_name", return_value="example-com"):
                with patch("app.api.configs_browser.serialize_browser_session") as mock_serialize:
                    mock_serialize.return_value = {
                        "id": "some-id",
                        "site_host": "example.com",
                        "status": "needs_login",
                    }
                    with patch("app.api.configs_browser.bind_browser_session_to_sources", new_callable=AsyncMock, return_value=2):
                        resp = await client.post(
                            "/api/configs/browser-sessions",
                            json={"site_url": "https://example.com", "auto_bind_sources": True},
                        )
                        assert resp.status_code == 200
                        assert resp.json()["bound_sources"] == 2


# ---------------------------------------------------------------------------
# POST /browser-sessions/{id}/open-login
# ---------------------------------------------------------------------------

class TestOpenBrowserSessionLogin:

    @pytest.mark.asyncio
    async def test_session_not_found(self, client: AsyncClient):
        fake_id = str(uuid4())
        resp = await client.post(f"/api/configs/browser-sessions/{fake_id}/open-login", json={})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_successful_bootstrap(self, client: AsyncClient, _db_factory, tmp_path):
        async with _db_factory() as db:
            session = BrowserSession(
                site_url="https://example.com",
                site_host="example.com",
                profile_name="example-com",
                user_data_dir=str(tmp_path / "example-com"),
                storage_state_path=str(tmp_path / "example-com" / "storage_state.json"),
                status=BrowserSessionStatus.NEEDS_LOGIN,
            )
            db.add(session)
            await db.commit()
            session_id = session.id

        with patch("app.api.configs_browser.extract_auth_cookies_for_host", return_value={}):
            with patch("app.api.configs_browser.run_browser_bootstrap", new_callable=AsyncMock) as mock_boot:
                mock_boot.return_value = {"final_url": "https://example.com", "title": "Example", "cookie_count": 5}
                with patch("app.api.configs_browser.serialize_browser_session") as mock_serialize:
                    mock_serialize.return_value = {"id": str(session_id), "status": "active"}
                    resp = await client.post(
                        f"/api/configs/browser-sessions/{session_id}/open-login",
                        json={"headless": True},
                    )
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["status"] == "active"
                    assert "bootstrap" in data

    @pytest.mark.asyncio
    async def test_bootstrap_failure_headless_mode(self, client: AsyncClient, _db_factory, tmp_path):
        async with _db_factory() as db:
            session = BrowserSession(
                site_url="https://example.com",
                site_host="example.com",
                profile_name="example-com",
                user_data_dir=str(tmp_path / "example-com"),
                storage_state_path=str(tmp_path / "example-com" / "storage_state.json"),
                status=BrowserSessionStatus.NEEDS_LOGIN,
            )
            db.add(session)
            await db.commit()
            session_id = session.id

        with patch("app.api.configs_browser.extract_auth_cookies_for_host", return_value={}):
            with patch("app.api.configs_browser.run_browser_bootstrap", new_callable=AsyncMock, side_effect=Exception("browser error")):
                resp = await client.post(
                    f"/api/configs/browser-sessions/{session_id}/open-login",
                    json={"headless": True},
                )
                assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_x_headless_login_is_rejected_before_bootstrap(self, client: AsyncClient, _db_factory, tmp_path):
        async with _db_factory() as db:
            session = BrowserSession(
                site_url="https://x.com",
                site_host="x.com",
                profile_name="x-com",
                user_data_dir=str(tmp_path / "x-com"),
                storage_state_path=str(tmp_path / "x-com" / "storage_state.json"),
                status=BrowserSessionStatus.NEEDS_LOGIN,
            )
            db.add(session)
            await db.commit()
            session_id = session.id

        with patch("app.api.configs_browser.ensure_x_shared_auth_config", new_callable=AsyncMock, return_value=None), \
             patch("app.api.configs_browser.run_browser_bootstrap", new_callable=AsyncMock) as mock_boot:
            resp = await client.post(
                f"/api/configs/browser-sessions/{session_id}/open-login",
                json={"headless": True},
            )

        assert resp.status_code == 422
        assert "X 登录必须使用可视化浏览器" in resp.json()["detail"]
        mock_boot.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_headful_display_error_is_actionable(self, client: AsyncClient, _db_factory, tmp_path):
        async with _db_factory() as db:
            session = BrowserSession(
                site_url="https://example.com",
                site_host="example.com",
                profile_name="example-com",
                user_data_dir=str(tmp_path / "example-com"),
                storage_state_path=str(tmp_path / "example-com" / "storage_state.json"),
                status=BrowserSessionStatus.NEEDS_LOGIN,
            )
            db.add(session)
            await db.commit()
            session_id = session.id

        detail = "可视化浏览器无法启动：当前 Linux/VPS 环境没有 DISPLAY/WAYLAND_DISPLAY。"
        with patch("app.api.configs_browser.extract_auth_cookies_for_host", return_value={}), \
             patch(
                 "app.api.configs_browser.run_browser_bootstrap",
                 new_callable=AsyncMock,
                 side_effect=HeadfulBrowserUnavailableError(detail),
             ):
            resp = await client.post(
                f"/api/configs/browser-sessions/{session_id}/open-login",
                json={"headless": False},
            )

        assert resp.status_code == 503
        assert "DISPLAY" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /browser-sessions/{id}/validate
# ---------------------------------------------------------------------------

class TestValidateBrowserSession:

    @pytest.mark.asyncio
    async def test_session_not_found(self, client: AsyncClient):
        fake_id = str(uuid4())
        resp = await client.post(f"/api/configs/browser-sessions/{fake_id}/validate", json={})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_successful_validation(self, client: AsyncClient, _db_factory, tmp_path):
        async with _db_factory() as db:
            session = BrowserSession(
                site_url="https://example.com",
                site_host="example.com",
                profile_name="example-com",
                user_data_dir=str(tmp_path / "example-com"),
                storage_state_path=str(tmp_path / "example-com" / "storage_state.json"),
                status=BrowserSessionStatus.ACTIVE,
            )
            db.add(session)
            await db.commit()
            session_id = session.id

        with patch("app.api.configs_browser.run_browser_validation", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = {
                "status": BrowserSessionStatus.ACTIVE,
                "message": "OK",
                "final_url": "https://example.com",
                "title": "Example",
                "cookie_count": 10,
                "paragraph_count": 5,
                "cookies": [],
            }
            with patch("app.api.configs_browser.serialize_browser_session") as mock_serialize:
                mock_serialize.return_value = {"id": str(session_id), "status": "active"}
                resp = await client.post(
                    f"/api/configs/browser-sessions/{session_id}/validate",
                    json={"sync_cookies_to_auth_config": False},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert "validation" in data

    @pytest.mark.asyncio
    async def test_validation_exception(self, client: AsyncClient, _db_factory, tmp_path):
        async with _db_factory() as db:
            session = BrowserSession(
                site_url="https://example.com",
                site_host="example.com",
                profile_name="example-com",
                user_data_dir=str(tmp_path / "example-com"),
                storage_state_path=str(tmp_path / "example-com" / "storage_state.json"),
                status=BrowserSessionStatus.ACTIVE,
            )
            db.add(session)
            await db.commit()
            session_id = session.id

        with patch("app.api.configs_browser.run_browser_validation", new_callable=AsyncMock, side_effect=Exception("fail")):
            resp = await client.post(
                f"/api/configs/browser-sessions/{session_id}/validate",
                json={},
            )
            assert resp.status_code == 500
