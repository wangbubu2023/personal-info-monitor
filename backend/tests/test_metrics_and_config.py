from __future__ import annotations

import pytest

from app.config import CorsOriginConfigError, parse_cors_origins


def test_parse_cors_origins_deduplicates_and_splits_lines():
    parsed = parse_cors_origins("http://a.test,\nhttp://b.test,http://a.test")
    assert parsed == ["http://a.test", "http://b.test"]


def test_parse_cors_origins_rejects_wildcard():
    with pytest.raises(CorsOriginConfigError):
        parse_cors_origins("*")


def test_parse_cors_origins_rejects_wildcard_subdomain():
    with pytest.raises(CorsOriginConfigError):
        parse_cors_origins("https://*.example.com")


def test_parse_cors_origins_rejects_missing_scheme():
    with pytest.raises(CorsOriginConfigError):
        parse_cors_origins("example.com")


def test_parse_cors_origins_accepts_tauri_scheme():
    parsed = parse_cors_origins("tauri://localhost")
    assert parsed == ["tauri://localhost"]


@pytest.mark.asyncio
async def test_prometheus_metrics_endpoint_exposes_text_format(client):
    await client.get("/api/sources")

    response = await client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "pim_http_requests_total" in response.text
    assert "pim_scheduler_running" in response.text
