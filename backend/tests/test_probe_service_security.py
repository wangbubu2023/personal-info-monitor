from __future__ import annotations

import types
from typing import List
from unittest.mock import AsyncMock

import pytest
from yarl import URL as YarlURL

from app.services.probe_service import ProbeService


@pytest.mark.asyncio
async def test_probe_service_blocks_private_resolution(monkeypatch):
    service = ProbeService()

    async def _fake_resolve(_hostname: str, _port: int) -> List[str]:
        return ["127.0.0.1"]

    monkeypatch.setattr("app.platform.security.ssrf._resolve_host_addresses", _fake_resolve)

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

    async def _fake_resolve(hostname: str, _port: int) -> List[str]:
        return ["93.184.216.34"] if hostname == "example.com" else ["127.0.0.1"]

    monkeypatch.setattr("app.platform.security.ssrf._resolve_host_addresses", _fake_resolve)
    monkeypatch.setattr(
        "app.services.probe_service.aiohttp.ClientSession",
        lambda *args, **kwargs: _FakeSession(),
    )

    result = await service._http_get("http://example.com")
    assert result is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("debug", "expected_ssl"),
    [
        (False, None),
        (True, False),
    ],
)
async def test_probe_disable_ssl_verify_only_applies_in_debug(monkeypatch, debug, expected_ssl):
    service = ProbeService()
    monkeypatch.setattr("app.services.probe_service.settings.probe_disable_ssl_verify", True)
    monkeypatch.setattr("app.services.probe_service.settings.debug", debug)
    monkeypatch.setattr(service, "_assert_public_http_target", AsyncMock(return_value=None))

    class _FakeResponse:
        status = 200
        url = "https://example.com"

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self):
            return "ok"

    captured: list[dict] = []

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def get(self, url, **kwargs):
            captured.append(kwargs)
            return _FakeResponse()

    monkeypatch.setattr(
        "app.services.probe_service.aiohttp.ClientSession",
        lambda *args, **kwargs: _FakeSession(),
    )

    result = await service._http_get("https://example.com")

    assert result == "ok"
    assert captured[0]["ssl"] is expected_ssl


@pytest.mark.asyncio
async def test_probe_attaches_cookies_when_provided(monkeypatch):
    """``probe(cookies=...)`` must surface the cookies into the aiohttp session."""
    service = ProbeService()
    monkeypatch.setattr(service, "_assert_public_http_target", AsyncMock(return_value=None))

    class _FakeResponse:
        status = 200
        url = "https://paywall.test"

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self):
            return "<html>paid-content</html>"

    captured_jars: list = []

    class _FakeSession:
        def __init__(self, **kwargs):
            captured_jars.append(kwargs.get("cookie_jar"))

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def get(self, url, **kwargs):
            return _FakeResponse()

    monkeypatch.setattr(
        "app.services.probe_service.aiohttp.ClientSession",
        lambda **kw: _FakeSession(**kw),
    )

    # Drive through the public entrypoint so the ContextVar wiring is exercised.
    async def _fake_probe(url):
        # Mimic a strategy that only calls _http_get once.
        return await service._http_get(url)

    monkeypatch.setattr(service, "_probe_website", _fake_probe)

    result = await service.probe(
        "https://paywall.test/article",
        "website",
        cookies={"session_id": "abc123", "": "skip-empty", "user": "u"},
    )

    assert result == "<html>paid-content</html>"
    assert len(captured_jars) == 1
    jar = captured_jars[0]
    assert jar is not None, "cookie jar should be attached when cookies are supplied"
    # Cookies must be scoped to the probe target host.
    filtered = jar.filter_cookies(YarlURL("https://paywall.test/article"))
    assert filtered.get("session_id") is not None
    assert filtered["session_id"].value == "abc123"
    assert filtered.get("user") is not None
    assert filtered["user"].value == "u"
    # Empty key must be dropped.
    assert filtered.get("") is None


@pytest.mark.asyncio
async def test_probe_without_cookies_keeps_default_session(monkeypatch):
    """No cookies → session gets the header-limit defaults but no cookie_jar."""
    service = ProbeService()
    monkeypatch.setattr(service, "_assert_public_http_target", AsyncMock(return_value=None))

    class _FakeResponse:
        status = 200
        url = "https://example.com"

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self):
            return "ok"

    captured_kwargs: list = []

    class _FakeSession:
        def __init__(self, **kwargs):
            captured_kwargs.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def get(self, url, **kwargs):
            return _FakeResponse()

    monkeypatch.setattr(
        "app.services.probe_service.aiohttp.ClientSession",
        lambda **kw: _FakeSession(**kw),
    )

    result = await service._http_get("https://example.com")

    assert result == "ok"
    assert len(captured_kwargs) == 1
    # The permissive header-limit defaults are always applied…
    assert captured_kwargs[0].get("max_line_size") and captured_kwargs[0].get("max_field_size")
    # …but no cookie jar should be attached when the caller supplied no cookies.
    assert "cookie_jar" not in captured_kwargs[0]
