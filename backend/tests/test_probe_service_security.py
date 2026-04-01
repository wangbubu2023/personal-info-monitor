from __future__ import annotations

import types

import pytest

from app.services.probe_service import ProbeService


@pytest.mark.asyncio
async def test_probe_service_blocks_private_resolution(monkeypatch):
    service = ProbeService()

    async def _fake_resolve(_hostname: str, _port: int) -> set[str]:
        return {"127.0.0.1"}

    monkeypatch.setattr(service, "_resolve_host_addresses", _fake_resolve)

    with pytest.raises(ValueError, match="private address"):
        await service._assert_public_http_target("http://example.com")


@pytest.mark.asyncio
async def test_probe_service_blocks_redirects_to_private_hosts(monkeypatch):
    service = ProbeService()

    class _FakeResponse:
        def __init__(self, status, headers=None, url="http://example.com"):
            self.status = status
            self.headers = headers or {}
            self.url = url

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self):
            return "ok"

    class _FakeSession:
        def __init__(self):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            if len(self.calls) == 1:
                return _FakeResponse(302, headers={"Location": "http://127.0.0.1/admin"}, url=url)
            raise AssertionError("private redirect should be blocked before the second request")

    async def _fake_resolve(hostname: str, _port: int) -> set[str]:
        return {"93.184.216.34"} if hostname == "example.com" else {"127.0.0.1"}

    monkeypatch.setattr(service, "_resolve_host_addresses", _fake_resolve)
    monkeypatch.setattr("app.services.probe_service.aiohttp.ClientSession", lambda: _FakeSession())

    result = await service._http_get("http://example.com")
    assert result is None
