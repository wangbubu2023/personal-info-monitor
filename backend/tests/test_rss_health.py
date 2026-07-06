"""Tests for RSS feed health + discovery-cache helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.domains.fetch.rss_health import (
    assess_feed_health,
    feed_health_metadata,
    persist_discovered_feed,
    record_feed_health,
)
from app.interfaces.http.sources._helpers import serialize_source
from app.models.source import Source, SourceType


def _source(metadata=None):
    return SimpleNamespace(metadata_=dict(metadata or {}))


def _orm_source(metadata=None):
    return Source(
        name="Example",
        type=SourceType.RSS,
        url="https://example.com/feed",
        fetch_interval=60,
        enabled=True,
        auth_required=False,
        error_count=0,
        metadata_=dict(metadata or {}),
    )


def test_parse_error_is_unhealthy():
    h = assess_feed_health(parse_ok=False, item_count=0, latest_published=None)
    assert h.status == "parse_error"
    assert h.healthy is False


def test_empty_feed():
    h = assess_feed_health(parse_ok=True, item_count=0, latest_published=None)
    assert h.status == "empty"
    assert h.healthy is False


def test_fresh_feed_ok():
    now = datetime(2026, 6, 1, 12, 0, 0)
    h = assess_feed_health(parse_ok=True, item_count=10, latest_published=now - timedelta(days=2), now=now)
    assert h.status == "ok"
    assert h.healthy is True
    assert h.stale_days == 2


def test_stale_feed_is_healthy_but_stale():
    now = datetime(2026, 6, 1, 12, 0, 0)
    h = assess_feed_health(parse_ok=True, item_count=10, latest_published=now - timedelta(days=60), now=now)
    assert h.status == "stale"
    # Stale != failure: still "healthy" so the source isn't marked failed.
    assert h.healthy is True
    assert h.stale_days == 60


def test_items_without_dates_are_ok():
    h = assess_feed_health(parse_ok=True, item_count=5, latest_published=None)
    assert h.status == "ok"
    assert h.stale_days is None


def test_record_feed_health_writes_metadata():
    src = _source()
    now = datetime(2026, 6, 1, 12, 0, 0)
    h = assess_feed_health(parse_ok=True, item_count=3, latest_published=now, now=now)
    record_feed_health(src, h, feed_url="https://x/feed")
    assert src.metadata_["rss_health"]["status"] == "ok"
    assert src.metadata_["rss_health"]["feed_url"] == "https://x/feed"


def test_record_feed_health_mirrors_structured_source_columns():
    src = _orm_source()
    now = datetime(2026, 6, 1, 12, 0, 0)
    h = assess_feed_health(parse_ok=True, item_count=3, latest_published=now, now=now)

    record_feed_health(src, h, feed_url="https://x/feed")

    assert src.rss_health_status == "ok"
    assert src.rss_health_healthy is True
    assert src.rss_health_item_count == 3
    assert src.rss_health_last_update == now
    assert src.rss_health_stale_days == 0
    assert src.rss_health_reason == "fresh"
    assert src.rss_health_checked_at is not None
    assert src.rss_health_feed_url == "https://x/feed"


def test_structured_rss_health_is_authoritative_for_source_serialization():
    src = _orm_source({"rss_health": {"status": "parse_error", "feed_url": "https://old/feed"}})
    src.rss_health_status = "stale"
    src.rss_health_healthy = True
    src.rss_health_item_count = 5
    src.rss_health_last_update = datetime(2026, 5, 1, 12, 0, 0)
    src.rss_health_stale_days = 31
    src.rss_health_reason = "no_recent_items"
    src.rss_health_checked_at = datetime(2026, 6, 1, 12, 0, 0)
    src.rss_health_feed_url = "https://new/feed"

    health = feed_health_metadata(src)
    serialized = serialize_source(src)

    assert health["status"] == "stale"
    assert health["feed_url"] == "https://new/feed"
    assert serialized["metadata"]["rss_health"]["status"] == "stale"
    assert serialized["metadata"]["rss_health"]["feed_url"] == "https://new/feed"


def test_persist_discovered_feed():
    src = _source()
    assert persist_discovered_feed(src, "https://x/feed") is True
    assert src.metadata_["rss_url"] == "https://x/feed"
    assert "https://x/feed" in src.metadata_["rss_urls"]
    # Idempotent: same feed again does not change metadata.
    assert persist_discovered_feed(src, "https://x/feed") is False


def test_persist_discovered_feed_appends_multiple():
    src = _source({"rss_url": "https://x/feed1", "rss_urls": ["https://x/feed1"]})
    persist_discovered_feed(src, "https://x/feed2")
    assert "https://x/feed2" in src.metadata_["rss_urls"]
