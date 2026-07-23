from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.postprocess_job import PostprocessJob
from app.models.reliable_execution import NotificationDelivery, OutboxEvent, SchedulerRun
from app.utils.datetime import utcnow_naive


@pytest.fixture()
def reliable_session(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'm1.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    import app.platform.notifications.outbox as outbox
    import app.platform.persistence.lineage as lineage
    import app.platform.workers.postprocess_jobs as postprocess
    import app.platform.workers.scheduler_ledger as scheduler_ledger

    monkeypatch.setattr(outbox, "SessionLocal", factory)
    monkeypatch.setattr(lineage, "SessionLocal", factory)
    monkeypatch.setattr(postprocess, "SessionLocal", factory)
    monkeypatch.setattr(scheduler_ledger, "SessionLocal", factory)
    return factory


def test_postprocess_lease_heartbeat_and_stale_owner_cas(reliable_session):
    from app.platform.workers.postprocess_jobs import (
        acquire_postprocess_job,
        ensure_postprocess_job,
        heartbeat_postprocess_job,
        mark_postprocess_job_succeeded,
    )

    ensure_postprocess_job("content-lease", "finish:v7:fingerprint")
    first = acquire_postprocess_job("content-lease", "finish:v7:fingerprint", owner="worker-a", lease_seconds=10)
    assert first is not None
    assert heartbeat_postprocess_job(
        "content-lease",
        "finish:v7:fingerprint",
        first.owner,
        first.token,
        lease_seconds=10,
    )

    with reliable_session() as db:
        job = db.query(PostprocessJob).one()
        job.lease_expires_at = utcnow_naive() - timedelta(seconds=1)
        db.commit()

    second = acquire_postprocess_job("content-lease", "finish:v7:fingerprint", owner="worker-b")
    assert second is not None
    assert second.token != first.token
    assert not mark_postprocess_job_succeeded(
        "content-lease",
        "finish:v7:fingerprint",
        owner=first.owner,
        token=first.token,
    )
    assert mark_postprocess_job_succeeded(
        "content-lease",
        "finish:v7:fingerprint",
        owner=second.owner,
        token=second.token,
    )


@pytest.mark.asyncio
async def test_scheduler_run_key_deduplicates_side_effect(reliable_session):
    from app.platform.workers.scheduler_ledger import execute_scheduled

    calls = 0

    async def command():
        nonlocal calls
        calls += 1
        return {"job_ids": ["job-1"]}

    business_key = "daily-digest:2026-07-23"
    first = await execute_scheduled("daily-digest", command, business_run_key=business_key)
    second = await execute_scheduled("daily-digest", command, business_run_key=business_key)

    assert first["state"] == "succeeded"
    assert second["duplicate"] is True
    assert calls == 1
    with reliable_session() as db:
        run = db.query(SchedulerRun).one()
        assert run.created_job_ids == ["job-1"]


@pytest.mark.asyncio
async def test_outbox_commit_is_recoverable_and_delivery_is_idempotent(reliable_session, monkeypatch):
    from app.platform.notifications.outbox import dispatch_outbox_event, enqueue_email

    send = pytest.importorskip("unittest.mock").AsyncMock(return_value=True)
    monkeypatch.setattr("app.platform.notifications.smtp._send_email_direct", send)

    event_id = enqueue_email(
        "reader@example.com",
        "Daily digest",
        "<p>digest</p>",
        idempotency_key="digest:2026-07-23:reader",
        aggregate_type="digest",
        aggregate_id="2026-07-23",
    )
    assert await dispatch_outbox_event(event_id) is True
    assert await dispatch_outbox_event(event_id) is True
    assert send.await_count == 1

    with reliable_session() as db:
        event = db.query(OutboxEvent).one()
        delivery = db.query(NotificationDelivery).one()
        assert event.state == "delivered"
        assert delivery.state == "delivered"
        assert delivery.attempt == 1


@pytest.mark.asyncio
async def test_outbox_provider_failure_enters_retry_ledger(reliable_session, monkeypatch):
    from app.platform.notifications.outbox import dispatch_outbox_event, enqueue_email

    send = pytest.importorskip("unittest.mock").AsyncMock(return_value=False)
    monkeypatch.setattr("app.platform.notifications.smtp._send_email_direct", send)
    event_id = enqueue_email(
        "reader@example.com",
        "Alert",
        "<p>alert</p>",
        idempotency_key="alert:provider-failure",
    )
    assert await dispatch_outbox_event(event_id) is False
    with reliable_session() as db:
        event = db.query(OutboxEvent).one()
        delivery = db.query(NotificationDelivery).one()
        assert event.state == "retry_wait"
        assert delivery.state == "retry_wait"
        event.available_at = utcnow_naive() - timedelta(seconds=1)
        db.commit()


def test_scheduler_misfire_compensation_is_bounded(reliable_session):
    from app.platform.workers.scheduler_ledger import record_misfires

    now = utcnow_naive().replace(second=0, microsecond=0)
    result = record_misfires(
        "hourly",
        [now - timedelta(hours=value) for value in range(1, 6)],
        catch_up_window=timedelta(hours=4),
        max_compensation=2,
    )
    assert len(result["caught_up"]) == 2
    assert len(result["skipped"]) == 3


def test_lineage_traces_delivery_upstream_in_three_hops(reliable_session):
    from app.platform.persistence.lineage import add_lineage_edge, trace_lineage

    add_lineage_edge(
        from_type="fetch_job", from_id="fetch-1",
        to_type="content", to_id="content-1", relation="persisted",
    )
    add_lineage_edge(
        from_type="content", from_id="content-1",
        to_type="outbox", to_id="outbox-1", relation="emitted",
    )
    add_lineage_edge(
        from_type="outbox", from_id="outbox-1",
        to_type="delivery", to_id="delivery-1", relation="delivered_as",
    )

    rows = trace_lineage("delivery", "delivery-1", max_hops=3)
    assert [row["from_type"] for row in rows] == ["outbox", "content", "fetch_job"]


def test_diagnostic_sink_is_bounded_rotating_and_best_effort(tmp_path):
    from app.platform.observability.diagnostic_sink import DiagnosticSink

    sink = DiagnosticSink(
        tmp_path / "diagnostics",
        buffer_max=3,
        batch_size=2,
        rotate_bytes=120,
        disk_limit_bytes=300,
    )
    for index in range(10):
        assert sink.record("assignment", {"index": index, "text": "x" * 40})
    sink.close()

    files = list((tmp_path / "diagnostics").glob("diagnostics-*.jsonl"))
    assert files
    assert sum(path.stat().st_size for path in files) <= 500


@pytest.mark.asyncio
async def test_priority_write_queue_backpressure_and_drain():
    from app.platform.persistence.write_queue import AsyncWriteQueue

    queue = AsyncWriteQueue(maxsize=4, batch_size=2)
    await queue.start()
    order = []

    low = asyncio.create_task(queue.submit(lambda: order.append("low"), priority=100))
    high = asyncio.create_task(queue.submit(lambda: order.append("high"), priority=1))
    await asyncio.gather(low, high)
    assert await queue.drain(timeout=1)
    assert sorted(order) == ["high", "low"]


@pytest.mark.asyncio
async def test_graceful_shutdown_times_out_and_cancels_inflight(monkeypatch):
    from unittest.mock import MagicMock

    from app.platform.workers.queue import BoundedTaskQueue

    queue = BoundedTaskQueue(fetch_maxsize=1, process_maxsize=1)

    async def slow_handler(content_id, job_id):
        await asyncio.sleep(30)

    monkeypatch.setattr("app.platform.workers.postprocess_jobs.claim_postprocess_job", MagicMock(return_value=True))
    monkeypatch.setattr("app.platform.workers.postprocess_jobs.take_claimed_postprocess_lease", MagicMock(return_value=None))
    await queue.start_workers(fetch_workers=0, process_workers=1, process_handler=slow_handler)
    queue._process_queue.put_nowait(("slow", None))
    await asyncio.sleep(0)
    summary = await queue.stop_workers(grace_timeout=0.01)
    assert summary.timed_out is True
    assert summary.cancelled == 1
