"""Tests for Auth Bundle schema and import API."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

from app.models.browser_session import BrowserSessionStatus
from app.platform.auth.bundle import (
    AuthBundleError,
    build_auth_bundle,
    load_auth_bundle,
    validate_auth_bundle,
    write_auth_bundle,
)


def _cookie(name: str, value: str, domain: str) -> dict:
    return {
        "name": name,
        "value": value,
        "domain": domain,
        "path": "/",
        "expires": 4_102_444_800,
        "httpOnly": True,
        "secure": True,
        "sameSite": "Lax",
    }


def test_auth_bundle_filters_to_target_host_and_roundtrips(tmp_path: Path):
    bundle = build_auth_bundle(
        site_url="https://www.example.com/news",
        cookies=[
            _cookie("session", "abc", ".example.com"),
            _cookie("login", "def", "login.example.com"),
            _cookie("other", "nope", "other.test"),
        ],
        storage_state={
            "cookies": [
                _cookie("session", "abc", ".example.com"),
                _cookie("other", "nope", "other.test"),
            ],
            "origins": [
                {"origin": "https://example.com", "localStorage": [{"name": "token", "value": "1"}]},
                {"origin": "https://other.test", "localStorage": [{"name": "token", "value": "2"}]},
            ],
        },
    )

    assert bundle["site_host"] == "example.com"
    assert [c["name"] for c in bundle["cookies"]] == ["session", "login"]
    assert [o["origin"] for o in bundle["storage_state"]["origins"]] == ["https://example.com"]

    path = write_auth_bundle(tmp_path / "example.pim-auth-bundle.json", bundle)
    assert path.stat().st_mode & 0o777 == 0o600
    assert validate_auth_bundle(load_auth_bundle(path))["site_host"] == "example.com"


def test_auth_bundle_rejects_empty_cookie_set():
    with pytest.raises(AuthBundleError):
        build_auth_bundle(site_url="https://example.com", cookies=[], storage_state=None)


@pytest.mark.asyncio
async def test_import_auth_bundle_creates_cookie_auth_and_binds_source(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    monkeypatch.setattr("app.domains.fetch.auth.bundle_import.profiles_root", lambda: tmp_path)
    source_resp = await client.post(
        "/api/sources",
        json={
            "name": "Example Paywall",
            "type": "website",
            "url": "https://example.com/news",
            "fetch_interval": 60,
            "metadata": {},
        },
    )
    assert source_resp.status_code in (200, 201), source_resp.text
    source_id = source_resp.json()["id"]

    bundle = build_auth_bundle(
        site_url="https://example.com",
        cookies=[_cookie("session", "abc", ".example.com")],
        storage_state={
            "cookies": [_cookie("session", "abc", ".example.com")],
            "origins": [{"origin": "https://example.com", "localStorage": []}],
        },
        name="Example imported login",
    )
    resp = await client.post(
        "/api/configs/auth-bundles/import",
        json={"bundle": bundle},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["site_host"] == "example.com"
    assert data["cookie_count"] == 1
    assert data["storage_state_imported"] is True
    assert data["bound_sources"] == 1
    assert data["auth_config"]["auth_type"] == "cookie"
    assert data["auth_config"]["has_cookies"] is True
    assert data["auth_config"]["cookie_mode"] == "bundle"
    assert data["browser_session"]["site_host"] == "example.com"
    assert data["browser_session"]["session_mode"] == "storage_state"
    assert data["browser_session"]["status"] == BrowserSessionStatus.UNVERIFIED.value
    assert data["browser_session"]["last_validated_at"] is None

    storage_state_path = Path(data["browser_session"]["storage_state_path"])
    assert storage_state_path.is_file()

    source_get = await client.get(f"/api/sources/{source_id}")
    assert source_get.status_code == 200
    assert source_get.json()["auth_config_id"] == data["auth_config"]["id"]
