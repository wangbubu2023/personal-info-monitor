"""Tests for RSS feed health + discovery-cache helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.domains.fetch.rss_health import (
    assess_feed_health,
    dedupe_feed_entries,
    persist_discovered_feed,
    record_feed_health,
)


def _source(metadata=None):
    return SimpleNamespace(metadata_=dict(metadata or {}))


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


def test_dedupe_feed_entries_by_external_id():
    entries = [
        {"external_id": "a", "title": "A"},
        {"external_id": "a", "title": "A dup"},
        {"url": "https://x/b", "title": "B"},
        {"url": "https://x/b", "title": "B dup"},
    ]
    out = dedupe_feed_entries(entries)
    assert len(out) == 2
    assert out[0]["title"] == "A"
    assert out[1]["title"] == "B"
