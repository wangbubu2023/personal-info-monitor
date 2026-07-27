from __future__ import annotations

import pytest
from types import SimpleNamespace

from app.config import (
    CorsOriginConfigError,
    _default_cors_origins,
    effective_cors_origins,
    parse_cors_origins,
)


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


def test_default_origins_include_same_origin_production_server():
    parsed = parse_cors_origins(_default_cors_origins())

    assert "http://localhost:8000" in parsed
    assert "http://127.0.0.1:8000" in parsed


def test_public_url_origin_is_automatically_trusted_and_deduplicated():
    settings = SimpleNamespace(
        cors_origins="http://localhost:3000,https://pim.example.com",
        pim_public_url="HTTPS://PIM.EXAMPLE.COM/app/",
        pim_public_origin="https://legacy.example.com/path",
    )

    assert effective_cors_origins(settings) == [
        "http://localhost:3000",
        "https://pim.example.com",
        "https://legacy.example.com",
    ]


@pytest.mark.parametrize(
    "public_url",
    ["pim.example.com", "ftp://pim.example.com", "https://user:secret@pim.example.com"],
)
def test_public_url_rejects_unsafe_or_malformed_values(public_url):
    settings = SimpleNamespace(
        cors_origins="",
        pim_public_url=public_url,
        pim_public_origin="",
    )

    with pytest.raises(CorsOriginConfigError):
        effective_cors_origins(settings)


@pytest.mark.asyncio
async def test_prometheus_metrics_endpoint_exposes_text_format(client):
    await client.get("/api/sources")

    response = await client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "pim_http_requests_total" in response.text
    assert "pim_scheduler_running" in response.text
