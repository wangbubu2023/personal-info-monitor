from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.platform.auth import api_key as auth_module
from app.platform.auth import bootstrap_token as bootstrap_module


def _request(*, sec_fetch_site: str | None = None) -> Request:
    headers = []
    if sec_fetch_site:
        headers.append((b"sec-fetch-site", sec_fetch_site.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/contents",
            "headers": headers,
            "scheme": "https",
            "server": ("pim.example", 443),
        }
    )


def test_same_origin_browser_skips_web_auth_when_disabled(monkeypatch):
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: SimpleNamespace(pim_api_key="secret", pim_web_auth_required=False),
    )
    assert auth_module.verify_api_key(None, _request(sec_fetch_site="same-origin")) == "browser:same-origin"


def test_generic_and_cross_site_clients_still_require_auth(monkeypatch):
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: SimpleNamespace(pim_api_key="secret", pim_web_auth_required=False),
    )
    for request in (_request(), _request(sec_fetch_site="cross-site")):
        with pytest.raises(HTTPException) as exc_info:
            auth_module.verify_api_key(None, request)
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_session_probe_reports_not_required_without_cookie(monkeypatch):
    monkeypatch.setattr(
        bootstrap_module,
        "get_settings",
        lambda: SimpleNamespace(pim_web_auth_required=False),
    )
    result = await bootstrap_module.session_status(_request(sec_fetch_site="same-origin"))
    assert result == {"status": "not_required", "actor": "same-origin-browser"}


@pytest.mark.asyncio
async def test_session_probe_keeps_strict_mode(monkeypatch):
    monkeypatch.setattr(
        bootstrap_module,
        "get_settings",
        lambda: SimpleNamespace(pim_web_auth_required=True),
    )
    monkeypatch.setattr(bootstrap_module, "validate_web_session", lambda _token: None)
    with pytest.raises(HTTPException) as exc_info:
        await bootstrap_module.session_status(_request(sec_fetch_site="same-origin"))
    assert exc_info.value.status_code == 401
