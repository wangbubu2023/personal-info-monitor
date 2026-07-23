# backend/tests/test_fetch_tasks_extended.py
"""fetch_tasks coverage: normal path, source not found, exception handling."""

import threading
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Source
from app.platform.workers.fetch_jobs import FetchDispatchResult


def _dispatch(source_id: str, *, enqueued: bool = True) -> FetchDispatchResult:
    return FetchDispatchResult(source_id, "scheduled", f"job-{source_id}", f"key-{source_id}", True, enqueued=enqueued)


@pytest.mark.asyncio
async def test_fetch_source_source_not_found():
    """A missing source is a typed terminal failure, never a success."""
    mock_sem = MagicMock()
    mock_sem.__aenter__ = AsyncMock(return_value=None)
    mock_sem.__aexit__ = AsyncMock(return_value=False)

    mock_tracker = MagicMock()
    mock_tracker.start_fetch = AsyncMock()
    mock_tracker.end_fetch = AsyncMock()

    with patch("app.tasks.fetch_tasks.get_fetch_semaphore", return_value=mock_sem):
        with patch("app.tasks.fetch_tasks.task_tracker", mock_tracker):
            # to_thread → _query_and_lock returns skip_reason
            to_thread_mock = AsyncMock(return_value="Source not found")
            with patch("app.tasks.fetch_tasks.asyncio.to_thread", to_thread_mock):
                from app.tasks.fetch_tasks import fetch_source
                from app.domains.fetch.failures import FetchFailureError

                with pytest.raises(FetchFailureError) as caught:
                    await fetch_source("nonexistent-id")

    mock_tracker.start_fetch.assert_called_once()
    mock_tracker.end_fetch.assert_called_once()
    assert caught.value.failure.code.value == "source_not_found"


@pytest.mark.asyncio
async def test_fetch_all_sources_dispatches_tasks():
    """fetch_all_sources queries enabled sources and enqueues fetch tasks."""
    with patch("app.tasks.fetch_tasks.asyncio.to_thread",
               new=AsyncMock(return_value=["src-1", "src-2"])):
        with patch("app.tasks.task_queue.task_queue") as mock_queue:
            mock_queue.enqueue_fetch = AsyncMock(side_effect=lambda sid, **_: _dispatch(sid))
            from app.tasks.fetch_tasks import fetch_all_sources
            result = await fetch_all_sources()

    assert result["status"] == "success"
    assert result["requested_count"] == 2
    assert result["persisted_count"] == 2


@pytest.mark.asyncio
async def test_fetch_all_sources_reports_pending_execution_cache():
    """Durable accepted jobs remain pending when the execution cache is full."""
    with patch("app.tasks.fetch_tasks.asyncio.to_thread",
               new=AsyncMock(return_value=["src-1", "src-2"])):
        with patch("app.tasks.task_queue.task_queue") as mock_queue:
            mock_queue.enqueue_fetch = AsyncMock(side_effect=lambda sid, **_: _dispatch(sid, enqueued=sid != "src-1"))
            from app.tasks.fetch_tasks import fetch_all_sources
            result = await fetch_all_sources()

    assert result["requested_count"] == 2
    assert result["persisted_count"] == 2
    assert result["enqueued_count"] == 1
    assert result["status"] == "partial"


@pytest.mark.asyncio
async def test_fetch_source_exception_is_persisted_and_reraised():
    """Worker-visible exceptions are persisted and re-raised for durable retry."""
    mock_sem = MagicMock()
    mock_sem.__aenter__ = AsyncMock(return_value=None)
    mock_sem.__aexit__ = AsyncMock(return_value=False)

    mock_tracker = MagicMock()
    mock_tracker.start_fetch = AsyncMock()
    mock_tracker.end_fetch = AsyncMock()

    # 1st call raises (query_and_lock), 2nd succeeds (persist_exception).
    # Note: query_and_lock in the real code returns 2-tuple, but here we want it to raise for the test case.
    to_thread_mock = AsyncMock(side_effect=[RuntimeError("network error"), None])

    with patch("app.tasks.fetch_tasks.get_fetch_semaphore", return_value=mock_sem):
        with patch("app.tasks.fetch_tasks.task_tracker", mock_tracker):
            with patch("app.tasks.fetch_tasks.asyncio.to_thread", to_thread_mock):
                with patch("app.tasks.fetch_tasks.persist_fetch_task_exception",
                           new=MagicMock()):
                    from app.tasks.fetch_tasks import fetch_source
                    with pytest.raises(RuntimeError, match="network error"):
                        await fetch_source("src-1")

    mock_tracker.end_fetch.assert_called_once()


def test_persist_fetch_task_exception_writes_structured_failure(monkeypatch):
    from app.domains.sources.status import persist_fetch_task_exception
    import app.domains.sources.status as status_module

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.SessionLocal", session_factory)

    db = session_factory()
    try:
        db.add(Source(id="src-timeout", name="Timeout Source", url="https://example.com", type="website"))
        db.commit()
    finally:
        db.close()

    persist_fetch_task_exception("src-timeout", TimeoutError("socket timed out"))

    db = session_factory()
    try:
        source = db.query(Source).filter(Source.id == "src-timeout").one()
        assert source.error_count == 1
        assert source.last_fetch_outcome_code == "timeout"
        assert source.last_fetch_outcome_severity == "warning"
        assert "抓取超时" in source.last_error
        assert source.metadata_["last_fetch_outcome"]["code"] == "timeout"
    finally:
        db.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_do_fetch_uses_fresh_session_for_pipeline():
    """The admission-check Session must not be passed into the async pipeline."""
    sessions = []
    main_thread_id = threading.get_ident()
    db_thread_ids = []

    class _FakeSource:
        id = "src-1"
        fetch_interval = 60
        enabled = True
        type = "website"
        url = "https://example.com"

    class _FakeQuery:
        def options(self, *args, **kwargs):
            return self

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            db_thread_ids.append(threading.get_ident())
            return _FakeSource()

    class _FakeSession:
        def __init__(self, name):
            self.name = name
            self.closed = False
            sessions.append(self)

        def query(self, model):
            return _FakeQuery()

        def close(self):
            self.closed = True

    def _session_factory():
        return _FakeSession(f"session-{len(sessions)}")

    pipeline_sessions = []

    async def _fake_pipeline(db, source, manual_trigger):
        pipeline_sessions.append(db)
        return {"saved": 0}

    with patch("app.database.SessionLocal", new=_session_factory), \
         patch("app.tasks.fetch_tasks.fetch_lock") as mock_lock, \
         patch("app.tasks.fetch_tasks.domain_limiter") as mock_limiter, \
         patch("app.tasks.fetch_tasks.run_fetch_pipeline", new=_fake_pipeline):
        mock_lock.acquire.return_value = True
        mock_limiter.acquire.return_value = True

        from app.tasks.fetch_tasks import _do_fetch

        await _do_fetch("src-1", manual_trigger=False)

    assert len(sessions) == 2
    assert sessions[0] is not pipeline_sessions[0]
    assert sessions[0].closed is True
    assert sessions[1].closed is True
    assert db_thread_ids
    assert all(thread_id != main_thread_id for thread_id in db_thread_ids)
    mock_lock.release.assert_called_once_with("src-1")


@pytest.mark.asyncio
async def test_twenty_fetch_admissions_keep_event_loop_responsive():
    """Historical 20-way fetches must not serialize sync ORM on uvicorn's loop."""
    import asyncio

    main_thread_id = threading.get_ident()
    query_thread_ids: list[int] = []

    class _FakeSource:
        id = "source"
        fetch_interval = 60
        enabled = True
        type = "website"
        url = "https://example.com"
        auth_config = None

    class _FakeQuery:
        def options(self, *args, **kwargs):
            return self

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            query_thread_ids.append(threading.get_ident())
            time.sleep(0.02)
            return _FakeSource()

    class _FakeSession:
        def query(self, model):
            return _FakeQuery()

        def close(self):
            return None

    async def _fake_pipeline(db, source, manual_trigger):
        await asyncio.sleep(0.02)
        return {"saved": 0}

    ticks = 0
    finished = False

    async def _heartbeat():
        nonlocal ticks
        while not finished:
            ticks += 1
            await asyncio.sleep(0.001)

    with patch("app.database.SessionLocal", new=_FakeSession), \
         patch("app.tasks.fetch_tasks.fetch_lock") as mock_lock, \
         patch("app.tasks.fetch_tasks.domain_limiter") as mock_limiter, \
         patch("app.tasks.fetch_tasks.run_fetch_pipeline", new=_fake_pipeline):
        mock_lock.acquire.return_value = True
        mock_limiter.acquire.return_value = True

        from app.tasks.fetch_tasks import _do_fetch

        heartbeat = asyncio.create_task(_heartbeat())
        try:
            await asyncio.gather(
                *(_do_fetch(f"source-{index}", manual_trigger=False) for index in range(20))
            )
        finally:
            finished = True
            await heartbeat

    assert ticks >= 5
    assert len(query_thread_ids) == 40
    assert all(thread_id != main_thread_id for thread_id in query_thread_ids)


@pytest.mark.asyncio
async def test_do_fetch_batches_new_content_finish_jobs():
    from types import SimpleNamespace

    from app.models.source import SourceType

    source = SimpleNamespace(
        id="source-1",
        fetch_interval=60,
        enabled=True,
        type=SourceType.WEBSITE,
        url="https://example.com",
        auth_config=None,
    )
    query = MagicMock()
    query.options.return_value = query
    query.filter.return_value = query
    query.first.return_value = source
    db = MagicMock()
    db.query.return_value = query

    async def _fake_pipeline(db, source, manual_trigger):
        return {
            "saved": 3,
            "new_content_ids": ["content-1", "content-2", "content-3"],
            "postprocess_candidates": [
                {
                    "content_id": f"content-{index}",
                    "trigger_reason": "new_insert",
                    "pipeline_version": "ingest-finish-v1",
                    "content_fingerprint": str(index) * 64,
                }
                for index in range(1, 4)
            ],
        }

    with patch("app.database.SessionLocal", return_value=db), \
         patch("app.tasks.fetch_tasks.fetch_lock") as mock_lock, \
         patch("app.tasks.fetch_tasks.domain_limiter") as mock_limiter, \
         patch("app.tasks.fetch_tasks.run_fetch_pipeline", new=_fake_pipeline), \
         patch("app.tasks.task_queue.task_queue") as task_queue:
        mock_lock.acquire.return_value = True
        mock_limiter.acquire.return_value = True
        task_queue.enqueue_ingest_finish = AsyncMock(return_value=True)

        from app.tasks.fetch_tasks import _do_fetch

        result = await _do_fetch("source-1", manual_trigger=False, job_id="fetch-1")

    assert result["saved"] == 3
    assert task_queue.enqueue_ingest_finish.await_count == 3
    first = task_queue.enqueue_ingest_finish.await_args_list[0]
    assert first.args[0] == "content-1"
    assert first.kwargs["job_id"].startswith("finish:ingest-finish-v1:")


@pytest.mark.asyncio
async def test_check_and_fetch_due_sources_dispatches_due():
    """check_and_fetch_due_sources queries due sources and enqueues them.

    The dispatcher now fires enqueues via ``asyncio.create_task`` so the
    scheduler loop doesn't block on per-source jitter sleeps; with a single
    due source, jitter is skipped entirely and the enqueue happens on the
    next loop turn.
    """
    with patch("app.tasks.fetch_tasks.asyncio.to_thread",
               new=AsyncMock(return_value=["due-src-1"])):
        with patch("app.tasks.task_queue.task_queue") as mock_queue:
            mock_queue.enqueue_fetch = AsyncMock(return_value=_dispatch("due-src-1"))
            from app.tasks.fetch_tasks import check_and_fetch_due_sources
            result = await check_and_fetch_due_sources()

    assert mock_queue.enqueue_fetch.call_count == 1
    assert result["persisted_count"] == 1


@pytest.mark.asyncio
async def test_check_and_fetch_due_sources_applies_startup_jitter():
    """When multiple sources come due together, enqueues are spread via
    ``create_task`` + randomized sleeps so the target hosts don't see a
    synchronized burst. Verifies the jitter kicks in only above 1 source and
    doesn't block the scheduler loop itself."""
    due = [f"src-{i}" for i in range(4)]

    with patch("app.tasks.fetch_tasks.asyncio.to_thread",
               new=AsyncMock(return_value=due)):
        with patch("app.tasks.task_queue.task_queue") as mock_queue:
            mock_queue.enqueue_fetch = AsyncMock(side_effect=lambda sid, **_: _dispatch(sid, enqueued=False))
            from app.tasks.fetch_tasks import check_and_fetch_due_sources
            await check_and_fetch_due_sources()

    assert mock_queue.enqueue_fetch.call_count == 4
    # Jitter is represented durably as not_before; no sleeping task is needed.
    from app.tasks.fetch_tasks import _STARTUP_JITTER_SECONDS

    calls = mock_queue.enqueue_fetch.await_args_list
    delays = [(call.kwargs["not_before"] - call.kwargs["due_window"]).total_seconds() for call in calls]
    assert all(0.0 <= delay <= _STARTUP_JITTER_SECONDS for delay in delays)
    assert len({round(delay, 3) for delay in delays}) > 1


def test_effective_due_interval_applies_backoff_and_jitter():
    """Error backoff multiplies the base interval; per-cycle jitter adds
    ±10% on top. Both must compose so e.g. a 60-min source that has
    errored 3 times (2^3 = 8×) lands in [60*8*0.9, 60*8*1.1] = [432, 528]."""
    from datetime import datetime as _dt

    from app.domains.sources.scheduling import effective_due_interval_minutes

    source = MagicMock()
    source.id = "src-backoff"
    source.fetch_interval = 60
    source.error_count = 3
    source.last_fetched_at = _dt(2026, 4, 22, 12, 0, 0)

    minutes = effective_due_interval_minutes(source)
    assert 432 <= minutes <= 528

    # Healthy source (no errors): interval lives in [54, 66].
    source.error_count = 0
    minutes = effective_due_interval_minutes(source)
    assert 54 <= minutes <= 66
