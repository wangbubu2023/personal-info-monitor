from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.main import _normalize_request_id, _request_route_label, app
from app.middleware.api_rate_limit import APIRateLimitMiddleware
from app.platform.auth import api_key as auth_module


def test_verify_api_key_rejects_missing_server_configuration(monkeypatch):
    # Phase 5 step 8 relocated ``verify_api_key`` to ``app.platform.auth.api_key``.
    # The caller reads ``get_settings`` from the canonical module's local
    # binding, so the patch must target the canonical module — patching the
    # legacy ``app.auth`` re-export shim would only rebind the shim attribute.
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: SimpleNamespace(pim_api_key="")
    )

    with pytest.raises(HTTPException) as exc_info:
        auth_module.verify_api_key("anything")

    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_livez_is_public_and_health_requires_api_key():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        livez = await client.get("/livez")
        assert livez.status_code == 200
        assert livez.json()["status"] == "ok"

        health = await client.get("/health")
        assert health.status_code == 401


@pytest.mark.asyncio
async def test_local_token_rejects_request_without_bootstrap_token(monkeypatch):
    """Missing bootstrap token must 401, even for loopback callers."""
    from app import main as main_module

    monkeypatch.setattr(main_module.settings, "bootstrap_token", "known-token")

    transport = ASGITransport(app=app, client=("127.0.0.1", 0))
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        resp = await client.get("/local-token")
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_local_token_rejects_invalid_bootstrap_token(monkeypatch):
    from app import main as main_module

    monkeypatch.setattr(main_module.settings, "bootstrap_token", "known-token")

    transport = ASGITransport(app=app, client=("127.0.0.1", 0))
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        resp = await client.get("/local-token?bootstrap_token=wrong")
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_local_token_rejects_foreign_host_header(monkeypatch):
    """Host-header whitelist blocks DNS rebinding attacks."""
    from app import main as main_module

    monkeypatch.setattr(main_module.settings, "bootstrap_token", "known-token")
    monkeypatch.setattr(main_module.settings, "pim_api_key", "secret-api-key")

    transport = ASGITransport(app=app, client=("127.0.0.1", 0))
    async with AsyncClient(transport=transport, base_url="http://attacker.example.com") as client:
        resp = await client.get(
            "/local-token",
            headers={"X-Bootstrap-Token": "known-token"},
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_local_token_rejects_untrusted_origin(monkeypatch):
    from app import main as main_module

    monkeypatch.setattr(main_module.settings, "bootstrap_token", "known-token")

    transport = ASGITransport(app=app, client=("127.0.0.1", 0))
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        resp = await client.get(
            "/local-token",
            headers={
                "X-Bootstrap-Token": "known-token",
                "Origin": "https://evil.example.com",
            },
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_local_token_accepts_valid_bootstrap_and_loopback(monkeypatch):
    """Happy path: loopback client + matching host + valid token returns the API key."""
    from app import main as main_module

    monkeypatch.setattr(main_module.settings, "bootstrap_token", "known-token")
    monkeypatch.setattr(main_module.settings, "pim_api_key", "secret-api-key")

    transport = ASGITransport(app=app, client=("127.0.0.1", 0))
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        resp = await client.get(
            "/local-token",
            headers={"X-Bootstrap-Token": "known-token"},
        )
        assert resp.status_code == 200
        assert resp.json()["api_key"] == "secret-api-key"


@pytest.mark.asyncio
async def test_local_token_accepts_query_token(monkeypatch):
    from app import main as main_module

    monkeypatch.setattr(main_module.settings, "bootstrap_token", "known-token")
    monkeypatch.setattr(main_module.settings, "pim_api_key", "secret-api-key")

    transport = ASGITransport(app=app, client=("127.0.0.1", 0))
    async with AsyncClient(transport=transport, base_url="http://localhost:8000") as client:
        resp = await client.get("/local-token?bootstrap_token=known-token")
        assert resp.status_code == 200
        assert resp.json()["api_key"] == "secret-api-key"


@pytest.mark.asyncio
async def test_local_token_rejects_non_loopback_client(monkeypatch):
    from app import main as main_module

    monkeypatch.setattr(main_module.settings, "bootstrap_token", "known-token")

    transport = ASGITransport(app=app, client=("10.0.0.5", 0))
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        resp = await client.get(
            "/local-token",
            headers={"X-Bootstrap-Token": "known-token"},
        )
        assert resp.status_code == 403


def _build_request(client_host: str | None, host_header: str | None):
    """Helper: fabricate a minimal Starlette Request for _inject_bootstrap_meta."""
    from starlette.requests import Request as _Request

    headers: list[tuple[bytes, bytes]] = []
    if host_header is not None:
        headers.append((b"host", host_header.encode()))
    scope: dict = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
    }
    if client_host is not None:
        scope["client"] = (client_host, 0)
    return _Request(scope)


def test_inject_bootstrap_meta_adds_tag_for_loopback_with_allowed_host():
    from app.main import _inject_bootstrap_meta

    request = _build_request("127.0.0.1", "localhost:8000")
    html = "<html><head><title>PIM</title></head><body></body></html>"
    injected = _inject_bootstrap_meta(html, request, "shiny-token")

    assert 'name="pim-bootstrap-token"' in injected
    assert 'content="shiny-token"' in injected
    assert injected.index('pim-bootstrap-token') < injected.index('</head>')


def test_inject_bootstrap_meta_escapes_token_content():
    from app.main import _inject_bootstrap_meta

    request = _build_request("127.0.0.1", "127.0.0.1:8000")
    html = "<html><head></head><body></body></html>"
    injected = _inject_bootstrap_meta(html, request, 'evil"<tag>')

    assert 'evil"<tag>' not in injected
    assert 'content="evil&quot;&lt;tag&gt;"' in injected


def test_inject_bootstrap_meta_skips_non_loopback_caller():
    from app.main import _inject_bootstrap_meta

    request = _build_request("10.0.0.5", "localhost:8000")
    html = "<html><head></head><body></body></html>"

    assert _inject_bootstrap_meta(html, request, "token") == html


def test_inject_bootstrap_meta_skips_foreign_host_header():
    """DNS-rebinding spoofing attempts must not receive the token."""
    from app.main import _inject_bootstrap_meta

    request = _build_request("127.0.0.1", "attacker.example.com")
    html = "<html><head></head><body></body></html>"

    assert _inject_bootstrap_meta(html, request, "token") == html


def test_inject_bootstrap_meta_skips_when_token_missing():
    from app.main import _inject_bootstrap_meta

    request = _build_request("127.0.0.1", "localhost:8000")
    html = "<html><head></head><body></body></html>"

    assert _inject_bootstrap_meta(html, request, "") == html
    assert _inject_bootstrap_meta(html, request, "   ") == html


def test_inject_bootstrap_meta_handles_missing_head_tag():
    from app.main import _inject_bootstrap_meta

    request = _build_request("127.0.0.1", "localhost:8000")
    html = "<!doctype html><body>no head</body>"
    injected = _inject_bootstrap_meta(html, request, "token")

    assert injected.startswith('<meta name="pim-bootstrap-token"')


@pytest.mark.asyncio
async def test_local_token_fails_closed_when_bootstrap_token_empty(monkeypatch):
    """A misconfigured server (empty bootstrap token) must not leak keys."""
    from app import main as main_module

    monkeypatch.setattr(main_module.settings, "bootstrap_token", "")

    transport = ASGITransport(app=app, client=("127.0.0.1", 0))
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        resp = await client.get("/local-token?bootstrap_token=anything")
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_request_counters(client):
    await client.get("/livez")

    response = await client.get("/api/system/metrics")
    assert response.status_code == 200
    payload = response.json()

    assert payload["http"]["total_requests"] >= 1
    assert payload["http"]["top_routes"]["GET /livez"] >= 1
    assert "scheduler" in payload


def test_normalize_request_id_accepts_safe_value():
    assert _normalize_request_id("abc-123-XYZ") == "abc-123-XYZ"


def test_normalize_request_id_rejects_invalid_or_too_long_values():
    generated = _normalize_request_id("bad value with spaces")
    assert generated != "bad value with spaces"
    assert len(generated) == 32

    too_long = "a" * 65
    assert _normalize_request_id(too_long) != too_long


def test_request_route_label_prefers_route_template():
    scope = {"type": "http", "method": "GET", "path": "/api/contents/123"}
    from starlette.requests import Request

    req = Request(scope)
    req.scope["route"] = SimpleNamespace(path="/api/contents/{content_id}", path_format="/api/contents/{content_id}")
    assert _request_route_label(req) == "/api/contents/{content_id}"


@pytest.mark.asyncio
async def test_invalid_request_id_header_is_replaced(client):
    response = await client.get("/livez", headers={"X-Request-ID": "bad value with spaces"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "bad value with spaces"
    assert len(response.headers["X-Request-ID"]) == 32


def test_api_rate_limit_middleware_returns_429():
    async def ping(request):
        return PlainTextResponse("ok")

    star = Starlette(routes=[Route("/api/ping", ping)])
    star.add_middleware(APIRateLimitMiddleware, requests_per_minute=3)
    client = TestClient(star)
    for _ in range(3):
        assert client.get("/api/ping").status_code == 200
    assert client.get("/api/ping").status_code == 429


def test_api_rate_limit_middleware_disabled_when_rpm_zero():
    async def ping(request):
        return PlainTextResponse("ok")

    star = Starlette(routes=[Route("/api/ping", ping)])
    star.add_middleware(APIRateLimitMiddleware, requests_per_minute=0)
    client = TestClient(star)
    for _ in range(10):
        assert client.get("/api/ping").status_code == 200
