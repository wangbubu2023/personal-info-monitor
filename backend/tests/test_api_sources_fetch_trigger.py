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
from app.tasks.task_queue import task_queue
from app.platform.workers.fetch_jobs import FetchDispatchResult


@pytest.fixture
def stub_task_queue(monkeypatch):
    """Replace ``task_queue.enqueue_fetch`` with a recording stub."""
    calls: list[tuple[str, bool, str | None]] = []

    async def _fake_enqueue(sid: str, manual_trigger: bool = False, **kwargs):
        calls.append((sid, manual_trigger, kwargs.get("fetch_kind")))
        return FetchDispatchResult(sid, kwargs.get("fetch_kind") or "manual", f"job-{sid}", f"key-{sid}", True, enqueued=True)

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
    assert response.json()["state"] == "enqueued"
    assert response.json()["persisted"] is True
    assert stub_task_queue == [(source_id, True, "manual")]


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
    async def _full_enqueue(sid: str, manual_trigger: bool = False, **kwargs):
        return FetchDispatchResult(sid, "manual", "job-pending", "key", True, enqueued=False)

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

    assert response.status_code == 200
    assert response.json()["state"] == "pending"
    assert response.json()["persisted"] is True
    assert response.json()["enqueued"] is False


@pytest.mark.asyncio
async def test_trigger_fetch_reports_duplicate_business_job(
    client, db_session, monkeypatch, stub_task_queue
):
    """A repeated business window returns the durable duplicate state."""
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

    async def _duplicate(sid: str, manual_trigger: bool = False, **kwargs):
        return FetchDispatchResult(sid, "manual", "job-existing", "key", True, duplicate=True)

    monkeypatch.setattr(task_queue, "enqueue_fetch", _duplicate)

    response = await client.post(f"/api/sources/{source_id}/fetch")

    assert response.status_code == 200
    assert response.json()["state"] == "duplicate"
    assert response.json()["job_id"] == "job-existing"


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
    assert payload["requested_count"] >= 3
    assert payload["persisted_count"] >= 3
    assert payload["enqueued_count"] >= 3
    assert payload["rejected_count"] == 0
    enqueued_ids = {sid for sid, _, _ in stub_task_queue}
    assert set(created_ids).issubset(enqueued_ids)
    assert all(manual is True for _, manual, _ in stub_task_queue)
