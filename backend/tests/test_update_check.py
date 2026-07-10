from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.platform.runtime import update_check


class _FakeResponse:
    def __init__(self, payload: object, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = update_check.httpx.Request("GET", _FakeAsyncClient.requested_url or "https://api.github.com")
            response = update_check.httpx.Response(self.status_code, request=request)
            raise update_check.httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=request,
                response=response,
            )

    def json(self) -> object:
        return self._payload


class _FakeAsyncClient:
    payload: object = {}
    status_code: int = 200
    requested_url: str | None = None
    client_headers: dict[str, str] = {}

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        type(self).client_headers = dict(kwargs.get("headers") or {})

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str):
        type(self).requested_url = url
        return _FakeResponse(type(self).payload, type(self).status_code)


def test_is_newer_version_handles_v_prefix_and_prerelease():
    assert update_check.is_newer_version("v1.4.4", "1.4.3") is True
    assert update_check.is_newer_version("release-1.4.3", "1.4.3") is False
    assert update_check.is_newer_version("v1.4.3", "1.4.4") is False
    assert update_check.is_newer_version("v1.4.3", "1.4.3-rc.1") is True


@pytest.mark.asyncio
async def test_check_for_updates_reports_new_release(monkeypatch):
    _FakeAsyncClient.status_code = 200
    _FakeAsyncClient.payload = {
        "tag_name": "v1.4.4",
        "html_url": "https://github.com/wangbubu2023/personal-info-monitor/releases/tag/v1.4.4",
        "name": "release: 1.4.4",
        "body": "Bug fixes",
        "published_at": "2026-07-09T00:00:00Z",
    }
    monkeypatch.setattr(update_check.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(update_check, "current_version", lambda: "1.4.3")
    monkeypatch.setattr(
        update_check,
        "get_settings",
        lambda: SimpleNamespace(
            pim_update_check_repo="wangbubu2023/personal-info-monitor",
            pim_update_check_github_token="",
            pim_update_check_timeout_seconds=4.0,
        ),
    )

    result = await update_check.check_for_updates()

    assert result["status"] == "ok"
    assert result["current_version"] == "1.4.3"
    assert result["latest_version"] == "1.4.4"
    assert result["latest_tag"] == "v1.4.4"
    assert result["update_available"] is True
    assert result["release_notes"] == "Bug fixes"
    assert _FakeAsyncClient.requested_url == "https://api.github.com/repos/wangbubu2023/personal-info-monitor/releases/latest"
    assert "Authorization" not in _FakeAsyncClient.client_headers


@pytest.mark.asyncio
async def test_check_for_updates_uses_configured_github_token(monkeypatch):
    _FakeAsyncClient.payload = {
        "tag_name": "v1.5.0",
        "html_url": "https://github.com/wangbubu2023/personal-info-monitor/releases/tag/v1.5.0",
    }
    _FakeAsyncClient.status_code = 200
    monkeypatch.setattr(update_check.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(update_check, "current_version", lambda: "1.5.0")
    monkeypatch.setattr(
        update_check,
        "get_settings",
        lambda: SimpleNamespace(
            pim_update_check_repo="wangbubu2023/personal-info-monitor",
            pim_update_check_github_token="  github-token  ",
            pim_update_check_timeout_seconds=4.0,
        ),
    )

    result = await update_check.check_for_updates()

    assert result["status"] == "ok"
    assert _FakeAsyncClient.client_headers["Authorization"] == "Bearer github-token"


@pytest.mark.asyncio
async def test_check_for_updates_reports_http_error_as_error(monkeypatch):
    _FakeAsyncClient.payload = {"message": "API rate limit exceeded"}
    _FakeAsyncClient.status_code = 403
    monkeypatch.setattr(update_check.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(update_check, "current_version", lambda: "1.5.0")
    monkeypatch.setattr(
        update_check,
        "get_settings",
        lambda: SimpleNamespace(
            pim_update_check_repo="wangbubu2023/personal-info-monitor",
            pim_update_check_github_token="",
            pim_update_check_timeout_seconds=4.0,
        ),
    )

    result = await update_check.check_for_updates()

    assert result["status"] == "error"
    assert result["message"] == "GitHub update check failed: HTTP 403"


@pytest.mark.asyncio
async def test_check_for_updates_can_be_disabled(monkeypatch):
    _FakeAsyncClient.status_code = 200
    monkeypatch.setattr(update_check, "current_version", lambda: "1.4.3")
    monkeypatch.setattr(
        update_check,
        "get_settings",
        lambda: SimpleNamespace(pim_update_check_repo="", pim_update_check_timeout_seconds=4.0),
    )

    result = await update_check.check_for_updates()

    assert result["status"] == "disabled"
    assert result["update_available"] is False
    assert result["current_version"] == "1.4.3"
