# backend/tests/test_fetch_tasks_extended.py
"""fetch_tasks coverage: normal path, source not found, exception handling."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_fetch_source_source_not_found():
    """When source doesn't exist, _do_fetch returns error without raising."""
    mock_sem = MagicMock()
    mock_sem.__aenter__ = AsyncMock(return_value=None)
    mock_sem.__aexit__ = AsyncMock(return_value=False)

    mock_tracker = MagicMock()
    mock_tracker.start_fetch = AsyncMock()
    mock_tracker.end_fetch = AsyncMock()

    with patch("app.tasks.fetch_tasks.get_fetch_semaphore", return_value=mock_sem):
        with patch("app.tasks.fetch_tasks.task_tracker", mock_tracker):
            # 1st to_thread → _query_and_lock returns (source, skip_reason)
            # 2nd to_thread → _cleanup
            to_thread_mock = AsyncMock(side_effect=[(None, "Source not found"), None])
            with patch("app.tasks.fetch_tasks.asyncio.to_thread", to_thread_mock):
                from app.tasks.fetch_tasks import fetch_source
                # Should not raise
                await fetch_source("nonexistent-id")

    mock_tracker.start_fetch.assert_called_once()
    mock_tracker.end_fetch.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_all_sources_dispatches_tasks():
    """fetch_all_sources queries enabled sources and enqueues fetch tasks."""
    with patch("app.tasks.fetch_tasks.asyncio.to_thread",
               new=AsyncMock(return_value=["src-1", "src-2"])):
        with patch("app.tasks.fetch_tasks.fetch_lock") as mock_lock:
            mock_lock.is_locked.return_value = False
            with patch("app.tasks.task_queue.task_queue") as mock_queue:
                mock_queue.enqueue_fetch = AsyncMock(return_value=True)
                from app.tasks.fetch_tasks import fetch_all_sources
                result = await fetch_all_sources()

    assert result["status"] == "success"
    assert result["total"] == 2


@pytest.mark.asyncio
async def test_fetch_all_sources_skips_locked():
    """fetch_all_sources skips sources that are already locked."""
    with patch("app.tasks.fetch_tasks.asyncio.to_thread",
               new=AsyncMock(return_value=["src-1", "src-2"])):
        with patch("app.tasks.fetch_tasks.fetch_lock") as mock_lock:
            # src-1 is locked, src-2 is not
            mock_lock.is_locked.side_effect = lambda sid: sid == "src-1"
            with patch("app.tasks.task_queue.task_queue") as mock_queue:
                mock_queue.enqueue_fetch = AsyncMock(return_value=True)
                from app.tasks.fetch_tasks import fetch_all_sources
                result = await fetch_all_sources()

    assert result["total"] == 2
    assert result["scheduled"] == 1


@pytest.mark.asyncio
async def test_fetch_source_exception_is_caught():
    """Exception in asyncio.to_thread is caught and persisted without re-raising."""
    mock_sem = MagicMock()
    mock_sem.__aenter__ = AsyncMock(return_value=None)
    mock_sem.__aexit__ = AsyncMock(return_value=False)

    mock_tracker = MagicMock()
    mock_tracker.start_fetch = AsyncMock()
    mock_tracker.end_fetch = AsyncMock()

    # 1st call raises (query_and_lock), 2nd succeeds (persist_exception), 3rd succeeds (cleanup)
    # Note: query_and_lock in the real code returns 2-tuple, but here we want it to raise for the test case.
    to_thread_mock = AsyncMock(side_effect=[RuntimeError("network error"), None, None])

    with patch("app.tasks.fetch_tasks.get_fetch_semaphore", return_value=mock_sem):
        with patch("app.tasks.fetch_tasks.task_tracker", mock_tracker):
            with patch("app.tasks.fetch_tasks.asyncio.to_thread", to_thread_mock):
                with patch("app.tasks.fetch_tasks.persist_fetch_task_exception",
                           new=MagicMock()):
                    from app.tasks.fetch_tasks import fetch_source
                    await fetch_source("src-1")  # Must not raise

    mock_tracker.end_fetch.assert_called_once()


@pytest.mark.asyncio
async def test_check_and_fetch_due_sources_dispatches_due():
    """check_and_fetch_due_sources queries due sources and enqueues them.

    The dispatcher now fires enqueues via ``asyncio.create_task`` so the
    scheduler loop doesn't block on per-source jitter sleeps; with a single
    due source, jitter is skipped entirely and the enqueue happens on the
    next loop turn.
    """
    import asyncio as _asyncio

    with patch("app.tasks.fetch_tasks.asyncio.to_thread",
               new=AsyncMock(return_value=["due-src-1"])):
        with patch("app.tasks.fetch_tasks.fetch_lock") as mock_lock:
            mock_lock.is_locked.return_value = False
            with patch("app.tasks.task_queue.task_queue") as mock_queue:
                mock_queue.enqueue_fetch = AsyncMock(return_value=True)
                from app.tasks.fetch_tasks import check_and_fetch_due_sources
                await check_and_fetch_due_sources()
                # Fire-and-forget enqueue runs on the next event loop
                # iteration; await a tick to let it land.
                await _asyncio.sleep(0)

    assert mock_queue.enqueue_fetch.call_count > 0


@pytest.mark.asyncio
async def test_check_and_fetch_due_sources_applies_startup_jitter():
    """When multiple sources come due together, enqueues are spread via
    ``create_task`` + randomized sleeps so the target hosts don't see a
    synchronized burst. Verifies the jitter kicks in only above 1 source and
    doesn't block the scheduler loop itself."""
    import asyncio as _asyncio

    due = [f"src-{i}" for i in range(4)]
    sleep_calls: list[float] = []

    real_sleep = _asyncio.sleep

    async def spy_sleep(duration: float) -> None:
        sleep_calls.append(duration)
        # Collapse to an immediate yield so the test runs fast regardless
        # of the randomized delay.
        await real_sleep(0)

    with patch("app.tasks.fetch_tasks.asyncio.to_thread",
               new=AsyncMock(return_value=due)):
        with patch("app.tasks.fetch_tasks.fetch_lock") as mock_lock:
            mock_lock.is_locked.return_value = False
            with patch("app.tasks.task_queue.task_queue") as mock_queue, \
                 patch("app.tasks.fetch_tasks.asyncio.sleep", new=spy_sleep):
                mock_queue.enqueue_fetch = AsyncMock(return_value=True)
                from app.tasks.fetch_tasks import check_and_fetch_due_sources
                await check_and_fetch_due_sources()
                # Give the delayed-enqueue tasks a chance to run.
                for _ in range(5):
                    await real_sleep(0)

    assert mock_queue.enqueue_fetch.call_count == 4
    # One jitter-sleep per source and every delay must sit within the
    # configured window [0, _STARTUP_JITTER_SECONDS].
    from app.tasks.fetch_tasks import _STARTUP_JITTER_SECONDS

    assert len(sleep_calls) == 4
    assert all(0.0 <= d <= _STARTUP_JITTER_SECONDS for d in sleep_calls)
    # Sources must decorrelate — if every delay is identical, the jitter
    # isn't doing its job.
    assert len({round(d, 3) for d in sleep_calls}) > 1


def test_effective_due_interval_applies_backoff_and_jitter():
    """Error backoff multiplies the base interval; per-cycle jitter adds
    ±10% on top. Both must compose so e.g. a 60-min source that has
    errored 3 times (2^3 = 8×) lands in [60*8*0.9, 60*8*1.1] = [432, 528]."""
    from datetime import datetime as _dt

    from app.tasks.fetch_tasks import _effective_due_interval_minutes

    source = MagicMock()
    source.id = "src-backoff"
    source.fetch_interval = 60
    source.error_count = 3
    source.last_fetched_at = _dt(2026, 4, 22, 12, 0, 0)

    minutes = _effective_due_interval_minutes(source)
    assert 432 <= minutes <= 528

    # Healthy source (no errors): interval lives in [54, 66].
    source.error_count = 0
    minutes = _effective_due_interval_minutes(source)
    assert 54 <= minutes <= 66
