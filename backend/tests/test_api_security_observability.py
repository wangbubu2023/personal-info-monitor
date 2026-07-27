from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

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
async def test_long_lived_local_token_contract_is_retired():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/local-token?bootstrap_token=must-not-work")
    assert response.status_code == 410
    assert "api_key" not in response.text


def test_bootstrap_meta_injection_is_a_noop():
    from app.platform.auth.bootstrap_token import _inject_bootstrap_meta
    from starlette.requests import Request

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    html = "<html><head></head><body></body></html>"
    assert _inject_bootstrap_meta(html, request, "long-lived-secret") == html


@pytest.mark.asyncio
async def test_bootstrap_exchange_sets_httponly_cookie_and_replay_fails(monkeypatch, caplog):
    issued = SimpleNamespace(token="session-secret", session_id="session-1", actor="local-cli")
    exchange = __import__("app.platform.auth.bootstrap_token", fromlist=["x"])
    calls = [issued, None]
    monkeypatch.setattr(exchange, "exchange_bootstrap_code", lambda _code: calls.pop(0))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        first = await client.post("/bootstrap/exchange", json={"code": "one-time-code-123456"})
        replay = await client.post("/bootstrap/exchange", json={"code": "one-time-code-123456"})

    assert first.status_code == 200
    cookie = first.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    assert first.headers["cache-control"] == "no-store"
    assert "session-secret" not in first.text
    assert replay.status_code == 401
    assert "one-time-code-123456" not in caplog.text


@pytest.mark.asyncio
async def test_bootstrap_exchange_rejects_cross_site_origin_before_consuming_code(monkeypatch):
    exchange = __import__("app.platform.auth.bootstrap_token", fromlist=["x"])
    consume = MagicMock()
    monkeypatch.setattr(exchange, "exchange_bootstrap_code", consume)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        response = await client.post(
            "/bootstrap/exchange",
            json={"code": "one-time-code-123456"},
            headers={"Origin": "https://evil.example"},
        )

    assert response.status_code == 403
    consume.assert_not_called()


@pytest.mark.asyncio
async def test_bootstrap_exchange_trusts_configured_public_url(monkeypatch):
    exchange = __import__("app.platform.auth.bootstrap_token", fromlist=["x"])
    issued = SimpleNamespace(token="session-secret", session_id="session-1", actor="local-cli")
    consume = MagicMock(return_value=issued)
    monkeypatch.setattr(exchange, "exchange_bootstrap_code", consume)
    monkeypatch.setattr(
        exchange,
        "get_settings",
        lambda: SimpleNamespace(
            cors_origins="http://localhost:3000",
            pim_public_url="https://pim.example.com/app/",
            pim_public_origin="",
        ),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        response = await client.post(
            "/bootstrap/exchange",
            json={"code": "one-time-code-123456"},
            headers={"Origin": "https://pim.example.com"},
        )

    assert response.status_code == 200
    consume.assert_called_once_with("one-time-code-123456")


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_request_counters(client):
    await client.get("/livez")

    response = await client.get("/api/system/metrics")
    assert response.status_code == 200
    payload = response.json()

    assert payload["http"]["total_requests"] >= 1
    assert payload["http"]["top_routes"]["GET /livez"] >= 1
    assert "scheduler" in payload


@pytest.mark.asyncio
async def test_score_vocab_reload_endpoint(client):
    response = await client.post("/api/system/score-vocab/reload")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["vocab"]["lane_count"] >= 1


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
