from __future__ import annotations

import json
import zipfile
from io import BytesIO

import pytest


@pytest.mark.anyio
async def test_auth_assistant_pairing_and_bundle_import(client):
    create_response = await client.post("/api/auth-assistant/pairing-tokens", json={"ttl_minutes": 10})
    assert create_response.status_code == 200
    token_payload = create_response.json()
    assert token_payload["pairing_token"]
    assert token_payload["pairing_url"].startswith("pim-auth://pair?")

    pair_response = await client.post(
        "/api/auth-assistant/pair",
        json={
            "pairing_token": token_payload["pairing_token"],
            "device_name": "Test Mac",
            "app_version": "0.1.0",
        },
    )
    assert pair_response.status_code == 200
    pair_payload = pair_response.json()
    device_token = pair_payload["device_token"]
    assert device_token.startswith("paa_")
    assert pair_payload["capabilities"]["import_bundle"] is True

    reuse_response = await client.post(
        "/api/auth-assistant/pair",
        json={"pairing_token": token_payload["pairing_token"], "device_name": "Second"},
    )
    assert reuse_response.status_code == 409

    bundle = _auth_bundle()
    import_response = await client.post(
        "/api/auth-assistant/auth-bundles/import",
        headers={"Authorization": f"Bearer {device_token}"},
        json={"bundle": bundle, "bind_matching_sources": True, "create_browser_session": True},
    )
    assert import_response.status_code == 200
    import_payload = import_response.json()
    assert import_payload["site_host"] == "example.com"
    assert import_payload["cookie_count"] == 1
    assert import_payload["storage_state_imported"] is True
    assert import_payload["auth_config"]["site_url"] == "https://example.com"
    assert import_payload["browser_session"]["status"] == "unverified"
    assert import_payload["browser_session"]["session_mode"] == "storage_state"
    assert import_payload["browser_session"]["last_validated_at"] is None


@pytest.mark.anyio
async def test_auth_assistant_zip_import_requires_device_token(client):
    response = await client.post(
        "/api/auth-assistant/auth-exports/import",
        files={"file": ("auth.zip", _auth_export_zip(), "application/zip")},
    )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_auth_assistant_zip_import(client):
    token_response = await client.post("/api/auth-assistant/pairing-tokens", json={})
    pair_response = await client.post(
        "/api/auth-assistant/pair",
        json={"pairing_token": token_response.json()["pairing_token"], "device_name": "Zip test"},
    )
    device_token = pair_response.json()["device_token"]

    response = await client.post(
        "/api/auth-assistant/auth-exports/import",
        headers={"X-Auth-Assistant-Token": device_token},
        files={"file": ("auth.zip", _auth_export_zip(), "application/zip")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["imported_profiles"] == 1
    assert payload["profiles"][0]["site_host"] == "example.com"
    assert payload["warnings"] == []


def _auth_bundle() -> dict:
    return {
        "kind": "pim.auth_bundle",
        "version": 1,
        "name": "Example Auth",
        "site_url": "https://example.com",
        "site_host": "example.com",
        "created_at": "2026-07-09T00:00:00Z",
        "captured_with": {"tool": "test"},
        "cookies": [
            {
                "name": "session",
                "value": "abc",
                "domain": ".example.com",
                "path": "/",
                "secure": True,
            }
        ],
        "storage_state": {
            "cookies": [
                {
                    "name": "session",
                    "value": "abc",
                    "domain": ".example.com",
                    "path": "/",
                    "secure": True,
                }
            ],
            "origins": [],
        },
    }


def _auth_export_zip() -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "kind": "pim.auth_export",
                    "version": 1,
                    "profiles": [{"site_host": "example.com", "file": "profiles/example.auth.json"}],
                }
            ),
        )
        archive.writestr("profiles/example.auth.json", json.dumps(_auth_bundle()))
    return output.getvalue()
