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
            # Simulate to_thread returning a "not found" result
            with patch("app.tasks.fetch_tasks.asyncio.to_thread",
                       new=AsyncMock(return_value={"status": "error", "message": "Source not found"})):
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

    # First call raises (simulating fetch failure), second call succeeds (persist exception call)
    to_thread_mock = AsyncMock(side_effect=[RuntimeError("network error"), None])

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
    """check_and_fetch_due_sources queries due sources and enqueues them."""
    with patch("app.tasks.fetch_tasks.asyncio.to_thread",
               new=AsyncMock(return_value=["due-src-1"])):
        with patch("app.tasks.fetch_tasks.fetch_lock") as mock_lock:
            mock_lock.is_locked.return_value = False
            with patch("app.tasks.task_queue.task_queue") as mock_queue:
                mock_queue.enqueue_fetch = AsyncMock(return_value=True)
                from app.tasks.fetch_tasks import check_and_fetch_due_sources
                await check_and_fetch_due_sources()

    # Verify at least one source was scheduled for fetch
    assert mock_queue.enqueue_fetch.call_count > 0
