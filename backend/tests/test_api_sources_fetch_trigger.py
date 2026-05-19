"""Regression tests for the manual fetch endpoints after Phase 1 enqueue change.

Phase 1 step 8 replaced ``asyncio.create_task(fetch_all_sources(...))``
and ``asyncio.create_task(fetch_source(...))`` with explicit
``task_queue.enqueue_fetch`` calls so the bounded queue's back-pressure
applies to manual triggers exactly like it does to scheduled ticks.

These tests verify the new wiring without spinning the actual queue
workers.
"""

from __future__ import annotations

import pytest

from app.api.sources import _helpers as sources_helpers
from app.api.sources import fetch_import as fetch_import_api
from app.tasks.task_queue import task_queue


class _StubFetchLock:
    def __init__(self, *, locked_ids: set[str] | None = None):
        self.locked_ids = locked_ids or set()

    def is_locked(self, source_id: str) -> bool:
        return source_id in self.locked_ids


@pytest.fixture
def stub_task_queue(monkeypatch):
    """Replace ``task_queue.enqueue_fetch`` with a recording stub."""
    calls: list[tuple[str, bool]] = []

    async def _fake_enqueue(sid: str, manual_trigger: bool = False) -> bool:
        calls.append((sid, manual_trigger))
        return True

    monkeypatch.setattr(task_queue, "enqueue_fetch", _fake_enqueue)
    return calls


@pytest.mark.asyncio
async def test_trigger_fetch_enqueues_via_task_queue(
    client, db_session, monkeypatch, stub_task_queue
):
    """POST /api/sources/{id}/fetch should enqueue, not create_task."""
    async def _fake_probe(urls, source_type, **_):
        from types import SimpleNamespace
        result = SimpleNamespace(
            status="ok",
            strategy="rss",
            rss_url="https://example.com/feed.xml",
            message="ok",
            sample_count=1,
            to_dict=lambda: {"status": "ok", "strategy": "rss",
                             "rss_url": "https://example.com/feed.xml",
                             "message": "ok", "sample_count": 1,
                             "probed_at": "2026-01-01T00:00:00Z"},
        )
        return result, {urls[0]: "https://example.com/feed.xml"}, 1

    monkeypatch.setattr(sources_helpers, "_probe_urls", _fake_probe)
    monkeypatch.setattr(fetch_import_api, "fetch_lock", _StubFetchLock())

    create_response = await client.post(
        "/api/sources",
        json={
            "name": "Manual Fetch Source",
            "type": "rss",
            "url": "https://example.com/feed.xml",
            "fetch_interval": 60,
            "enabled": True,
            "auth_required": False,
            "extra_urls": [],
        },
    )
    assert create_response.status_code == 200, create_response.text
    source_id = create_response.json()["id"]

    response = await client.post(f"/api/sources/{source_id}/fetch")

    assert response.status_code == 200, response.text
    assert response.json() == {"message": "Fetch task dispatched", "source_id": source_id}
    assert stub_task_queue == [(source_id, True)]


@pytest.mark.asyncio
async def test_trigger_fetch_returns_503_when_queue_full(
    client, db_session, monkeypatch
):
    """Enqueue failure must surface as HTTP 503 instead of silently dropping."""
    async def _fake_probe(urls, source_type, **_):
        from types import SimpleNamespace
        result = SimpleNamespace(
            status="ok",
            strategy="rss",
            rss_url="https://example.com/feed.xml",
            message="ok",
            sample_count=1,
            to_dict=lambda: {"status": "ok", "strategy": "rss",
                             "rss_url": "https://example.com/feed.xml",
                             "message": "ok", "sample_count": 1,
                             "probed_at": "2026-01-01T00:00:00Z"},
        )
        return result, {urls[0]: "https://example.com/feed.xml"}, 1

    monkeypatch.setattr(sources_helpers, "_probe_urls", _fake_probe)
    monkeypatch.setattr(fetch_import_api, "fetch_lock", _StubFetchLock())

    async def _full_enqueue(sid: str, manual_trigger: bool = False) -> bool:
        return False

    monkeypatch.setattr(task_queue, "enqueue_fetch", _full_enqueue)

    create_response = await client.post(
        "/api/sources",
        json={
            "name": "Full Queue Source",
            "type": "rss",
            "url": "https://example.com/feed2.xml",
            "fetch_interval": 60,
            "enabled": True,
            "auth_required": False,
            "extra_urls": [],
        },
    )
    assert create_response.status_code == 200, create_response.text
    source_id = create_response.json()["id"]

    response = await client.post(f"/api/sources/{source_id}/fetch")

    assert response.status_code == 503
    assert "queue is full" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_trigger_fetch_skips_locked_source(
    client, db_session, monkeypatch, stub_task_queue
):
    """If the source is already being fetched, return idempotent message."""
    async def _fake_probe(urls, source_type, **_):
        from types import SimpleNamespace
        result = SimpleNamespace(
            status="ok",
            strategy="rss",
            rss_url="https://example.com/feed.xml",
            message="ok",
            sample_count=1,
            to_dict=lambda: {"status": "ok", "strategy": "rss",
                             "rss_url": "https://example.com/feed.xml",
                             "message": "ok", "sample_count": 1,
                             "probed_at": "2026-01-01T00:00:00Z"},
        )
        return result, {urls[0]: "https://example.com/feed.xml"}, 1

    monkeypatch.setattr(sources_helpers, "_probe_urls", _fake_probe)

    create_response = await client.post(
        "/api/sources",
        json={
            "name": "Locked Source",
            "type": "rss",
            "url": "https://example.com/feed3.xml",
            "fetch_interval": 60,
            "enabled": True,
            "auth_required": False,
            "extra_urls": [],
        },
    )
    assert create_response.status_code == 200, create_response.text
    source_id = create_response.json()["id"]

    monkeypatch.setattr(
        fetch_import_api,
        "fetch_lock",
        _StubFetchLock(locked_ids={source_id}),
    )

    response = await client.post(f"/api/sources/{source_id}/fetch")

    assert response.status_code == 200
    assert response.json() == {"message": "Fetch already running", "source_id": source_id}
    assert stub_task_queue == []  # nothing enqueued because the lock blocked us


@pytest.mark.asyncio
async def test_trigger_fetch_all_enqueues_visible_sources(
    client, db_session, monkeypatch, stub_task_queue
):
    """POST /api/sources/fetch-all enqueues every visible enabled source."""
    async def _fake_probe(urls, source_type, **_):
        from types import SimpleNamespace
        result = SimpleNamespace(
            status="ok",
            strategy="rss",
            rss_url=urls[0],
            message="ok",
            sample_count=1,
            to_dict=lambda: {"status": "ok", "strategy": "rss",
                             "rss_url": urls[0], "message": "ok",
                             "sample_count": 1,
                             "probed_at": "2026-01-01T00:00:00Z"},
        )
        return result, {urls[0]: urls[0]}, 1

    monkeypatch.setattr(sources_helpers, "_probe_urls", _fake_probe)
    monkeypatch.setattr(fetch_import_api, "fetch_lock", _StubFetchLock())

    created_ids: list[str] = []
    for idx in range(3):
        resp = await client.post(
            "/api/sources",
            json={
                "name": f"Bulk Source {idx}",
                "type": "rss",
                "url": f"https://example.com/feed-{idx}.xml",
                "fetch_interval": 60,
                "enabled": True,
                "auth_required": False,
                "extra_urls": [],
            },
        )
        assert resp.status_code == 200, resp.text
        created_ids.append(resp.json()["id"])

    response = await client.post("/api/sources/fetch-all")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["source_count"] >= 3
    assert payload["scheduled"] >= 3
    assert payload["dropped"] == 0
    enqueued_ids = {sid for sid, _ in stub_task_queue}
    assert set(created_ids).issubset(enqueued_ids)
    assert all(manual is True for _, manual in stub_task_queue)
