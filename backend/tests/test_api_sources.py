from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.api import sources as sources_api
from app.api.sources import _helpers as sources_helpers
from app.domains.fetch.session_health import SessionHealth, record_session_health
from app.domains.sources.status import set_last_fetch_outcome
from app.features import PODCAST_DISABLED_DETAIL
from app.models import BrowserSession, Content, Source
from app.models.browser_session import BrowserSessionMode, BrowserSessionStatus
from app.models.source_fetch_log import SourceFetchLog
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


def test_serialize_source_exposes_session_health_top_level():
    source = Source(
        name="X",
        type=SourceType.X,
        url="https://x.com/example",
        metadata_={
            "session_health": {
                "status": "error",
                "reason": "expired",
                "suggested_action": "relogin",
            }
        },
    )
    source.error_count = 0

    payload = sources_helpers.serialize_source(source)

    assert payload["session_health"]["reason"] == "expired"
    assert payload["metadata"]["session_health"]["suggested_action"] == "relogin"


def test_serialize_source_prefers_structured_session_health():
    source = Source(
        name="X",
        type=SourceType.X,
        url="https://x.com/example",
        error_count=0,
        metadata_={
            "session_health": {
                "status": "ok",
                "reason": "ok",
                "suggested_action": "none",
            }
        },
    )

    record_session_health(
        source,
        SessionHealth(
            status="error",
            reason="expired",
            suggested_action="relogin",
            validated_at="2026-07-03T10:00:00Z",
            details={"source": "x_graphql"},
        ),
    )
    source.metadata_["session_health"] = {
        "status": "ok",
        "reason": "ok",
        "suggested_action": "none",
    }
    payload = sources_helpers.serialize_source(source)

    assert source.session_health_status == "error"
    assert source.session_health_reason == "expired"
    assert payload["session_health"]["reason"] == "expired"
    assert payload["metadata"]["session_health"]["details"]["source"] == "x_graphql"


def test_serialize_source_prefers_structured_last_fetch_outcome():
    source = Source(
        name="Feed",
        type=SourceType.RSS,
        url="https://example.com/feed.xml",
        fetch_interval=60,
        enabled=True,
        auth_required=False,
        last_fetched_at=datetime(2026, 6, 1, 12, 0, 0),
        error_count=0,
        metadata_={"last_fetch_outcome": {"code": "stale", "severity": "warning", "message": "old"}},
    )

    set_last_fetch_outcome(source, "http_429", "error", "rate limited")
    source.metadata_["last_fetch_outcome"] = {"code": "stale", "severity": "warning", "message": "old"}
    payload = sources_helpers.serialize_source(source)

    assert source.last_fetch_outcome_code == "http_429"
    assert source.last_fetch_outcome_severity == "error"
    assert source.last_fetch_outcome_message == "rate limited"
    assert payload["metadata"]["last_fetch_outcome"]["code"] == "http_429"
    assert payload["fetch_status"] == "error"
    assert payload["fetch_status_message"] == "rate limited"


@pytest.mark.asyncio
async def test_paid_source_matrix_reports_slo_fields(client, db_session):
    source = Source(
        name="Example Paid",
        type=SourceType.WEBSITE,
        url="https://example.com/news",
        fetch_interval=60,
        enabled=True,
        auth_required=True,
        session_health_status="error",
        session_health_reason="expired",
        metadata_={"paid_source": {"validation_url": "https://example.com/paid/story", "discovery": "RSS + 网站"}},
    )
    session = BrowserSession(
        site_url="https://example.com",
        site_host="example.com",
        profile_name="example-paid",
        session_mode=BrowserSessionMode.PERSISTENT_PROFILE.value,
        status=BrowserSessionStatus.ACTIVE,
    )
    db_session.add_all([source, session])
    await db_session.flush()
    db_session.add(
        SourceFetchLog(
            source_id=str(source.id),
            outcome="success",
            saved_count=1,
            fulltext_ok=1,
            fulltext_total=1,
        )
    )
    await db_session.commit()

    response = await client.get("/api/sources/paid-matrix")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["source_name"] == "Example Paid"
    assert item["discovery"] == "RSS + 网站"
    assert item["body_path"] == "VPS persistent profile"
    assert item["validation_url"] == "https://example.com/paid/story"
    assert item["success_rate_7d"] == 1.0
    assert item["failure_code"] == "expired"
    assert "重新登录" in item["recovery_action"]


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
async def test_source_dry_run_endpoint_returns_diagnostics_without_writing(client, db_session, monkeypatch):
    source = Source(name="Dry Run Feed", type=SourceType.RSS, url="https://example.com/feed.xml")
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)

    async def _fake_dry_run(source_id, *, sample_limit=5):
        assert str(source_id) == str(source.id)
        assert sample_limit == 2
        return {
            "source_id": str(source_id),
            "source_name": "Dry Run Feed",
            "source_type": "rss",
            "dry_run": True,
            "would_write": False,
            "warnings": {"merged": None, "primary": None},
            "stages": {
                "collector": {"count": 1},
                "normalizer": {"input_count": 1, "valid_count": 1, "stale_skipped": 0, "other_skipped": 0},
                "builder": {"would_store_count": 1, "build_failed": 0},
            },
            "samples": {"raw": [], "would_store": []},
            "runtime": {"fetch_diag": None, "metadata_preview": {}},
        }

    from app.interfaces.http.sources import dry_run as dry_run_api

    monkeypatch.setattr(dry_run_api, "run_source_dry_run", _fake_dry_run)

    response = await client.post(f"/api/sources/{source.id}/dry-run", params={"sample_limit": 2})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["would_write"] is False
    assert payload["stages"]["builder"]["would_store_count"] == 1

    contents = (await db_session.execute(select(Content))).scalars().all()
    assert contents == []


@pytest.mark.asyncio
async def test_sources_page_size_has_explicit_upper_bound(client):
    response = await client.get("/api/sources", params={"page_size": 201})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_sources_returns_content_count_and_sorts(client, db_session):
    alpha = Source(name="Alpha", type=SourceType.RSS, url="https://example.com/alpha.xml")
    beta = Source(name="Beta", type=SourceType.RSS, url="https://example.com/beta.xml")
    empty = Source(name="Empty", type=SourceType.RSS, url="https://example.com/empty.xml")
    db_session.add_all([alpha, beta, empty])
    await db_session.flush()
    db_session.add_all(
        [
            Content(
                source_id=alpha.id,
                title="Alpha One",
                original_url="https://example.com/alpha-1",
                content_type="rss",
            ),
            Content(
                source_id=alpha.id,
                title="Alpha Two",
                original_url="https://example.com/alpha-2",
                content_type="rss",
            ),
            Content(
                source_id=beta.id,
                title="Beta One",
                original_url="https://example.com/beta-1",
                content_type="rss",
            ),
        ]
    )
    await db_session.commit()
    sources_api._invalidate_source_cache()

    response = await client.get(
        "/api/sources",
        params={"sort_by": "content_count", "sort_order": "descend", "page_size": 3},
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert [(item["name"], item["content_count"]) for item in items] == [
        ("Alpha", 2),
        ("Beta", 1),
        ("Empty", 0),
    ]


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
