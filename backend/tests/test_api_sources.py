from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api import sources as sources_api
from app.api.sources import _helpers as sources_helpers
from app.features import PODCAST_DISABLED_DETAIL
from app.models import Source
from app.models.source import SourceType


class _ProbeResult:
    def __init__(self, status: str = "ok", strategy: str = "rss", rss_url: str | None = None):
        self.status = status
        self.strategy = strategy
        self.rss_url = rss_url
        self.message = "ok"
        self.sample_count = 3

    def to_dict(self):
        return {
            "status": self.status,
            "strategy": self.strategy,
            "rss_url": self.rss_url,
            "message": self.message,
            "sample_count": self.sample_count,
            "probed_at": "2026-03-31T00:00:00Z",
        }


@pytest.mark.asyncio
async def test_sources_crud_and_list_cache_invalidation(client, db_session, monkeypatch):
    async def _fake_probe_urls(urls, source_type, **_):
        return _ProbeResult(rss_url="https://example.com/feed.xml"), {urls[0]: "https://example.com/feed.xml"}, 1

    monkeypatch.setattr(sources_helpers, "_probe_urls", _fake_probe_urls)

    create_response = await client.post(
        "/api/sources",
        json={
            "name": "Example Feed",
            "type": "website",
            "url": "https://example.com",
            "fetch_interval": 60,
            "enabled": True,
            "auth_required": False,
            "extra_urls": ["https://example.com/news"],
            "metadata": {"team": "alpha"},
        },
    )
    assert create_response.status_code == 200
    source_id = create_response.json()["id"]
    body = create_response.json()
    assert body["probe_status"] == "not_probed"
    assert body["fetch_status"] == "unknown"

    probe_response = await client.post(f"/api/sources/{source_id}/probe")
    assert probe_response.status_code == 200
    assert probe_response.json()["probe_status"] == "ok"
    assert probe_response.json()["metadata"]["rss_url"] == "https://example.com/feed.xml"

    first_list = await client.get("/api/sources")
    assert first_list.status_code == 200
    assert first_list.json()["total"] == 1

    cached_list = await client.get("/api/sources")
    assert cached_list.status_code == 200
    assert cached_list.json()["items"][0]["name"] == "Example Feed"

    update_response = await client.patch(
        f"/api/sources/{source_id}",
        json={"name": "Updated Feed", "extra_urls": ["https://example.com/latest"]},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Updated Feed"

    updated_list = await client.get("/api/sources")
    assert updated_list.status_code == 200
    assert updated_list.json()["items"][0]["name"] == "Updated Feed"
    assert updated_list.json()["items"][0]["extra_urls"] == ["https://example.com/latest"]

    delete_response = await client.delete(f"/api/sources/{source_id}")
    assert delete_response.status_code == 200

    final_list = await client.get("/api/sources")
    assert final_list.status_code == 200
    assert final_list.json()["total"] == 0


@pytest.mark.asyncio
async def test_sources_page_size_has_explicit_upper_bound(client):
    response = await client.get("/api/sources", params={"page_size": 201})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_probe_source_updates_fetch_status_and_invalidates_list_cache(client, db_session, monkeypatch):
    source = Source(name="Probe Me", type=SourceType.WEBSITE, url="https://example.com")
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)

    async def _fake_probe_urls(urls, source_type, **_):
        return _ProbeResult(strategy="scrape"), {}, 1

    monkeypatch.setattr(sources_helpers, "_probe_urls", _fake_probe_urls)

    warm = await client.get("/api/sources")
    assert warm.status_code == 200

    probe_response = await client.post(f"/api/sources/{source.id}/probe")
    assert probe_response.status_code == 200
    assert probe_response.json()["probe_strategy"] == "scrape"
    assert probe_response.json()["probe_status"] == "ok"
    assert probe_response.json()["fetch_status"] == "unknown"

    refreshed = await client.get("/api/sources")
    assert refreshed.status_code == 200
    assert refreshed.json()["items"][0]["probe_strategy"] == "scrape"


@pytest.mark.asyncio
async def test_podcast_sources_are_hidden_and_rejected(client, db_session):
    source = Source(name="Podcast Feed", type=SourceType.PODCAST, url="https://example.com/feed.xml")
    db_session.add(source)
    await db_session.commit()
    sources_api._invalidate_source_cache()

    create_response = await client.post(
        "/api/sources",
        json={
            "name": "New Podcast",
            "type": "podcast",
            "url": "https://example.com/podcast.xml",
            "fetch_interval": 60,
            "enabled": True,
            "auth_required": False,
            "extra_urls": [],
            "metadata": {},
        },
    )
    assert create_response.status_code == 409
    assert create_response.json()["detail"] == PODCAST_DISABLED_DETAIL

    list_response = await client.get("/api/sources")
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 0

    get_response = await client.get(f"/api/sources/{source.id}")
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_sources_metadata_max_fetch_lag_minutes(client, monkeypatch):
    async def _fake_probe_urls(urls, source_type, **_):
        return _ProbeResult(), {}, 1

    monkeypatch.setattr(sources_helpers, "_probe_urls", _fake_probe_urls)

    bad = await client.post(
        "/api/sources",
        json={
            "name": "Lag Bad",
            "type": "rss",
            "url": "https://example.com/lag-bad.xml",
            "metadata": {"max_fetch_lag_minutes": 0},
        },
    )
    assert bad.status_code == 422

    ok = await client.post(
        "/api/sources",
        json={
            "name": "Lag Ok",
            "type": "rss",
            "url": "https://example.com/lag-ok.xml",
            "metadata": {"max_fetch_lag_minutes": 1440},
        },
    )
    assert ok.status_code == 200
    assert ok.json()["metadata"].get("max_fetch_lag_minutes") == 1440

    sid = ok.json()["id"]
    cleared = await client.patch(
        f"/api/sources/{sid}",
        json={"metadata": {"max_fetch_lag_minutes": None}},
    )
    assert cleared.status_code == 200
    assert "max_fetch_lag_minutes" not in cleared.json().get("metadata", {})
