# backend/tests/test_task_queue.py
import asyncio
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_enqueue_fetch_returns_true_when_capacity_available():
    from app.tasks.task_queue import BoundedTaskQueue
    q = BoundedTaskQueue(fetch_maxsize=5, process_maxsize=5)
    await q.start_workers(fetch_workers=1, process_workers=1)
    try:
        with patch("app.tasks.fetch_tasks.fetch_source", new=AsyncMock()):
            result = await q.enqueue_fetch("source-1")
        assert result is True
    finally:
        await q.stop_workers()


@pytest.mark.asyncio
async def test_enqueue_fetch_returns_false_when_queue_full():
    from app.tasks.task_queue import BoundedTaskQueue
    q = BoundedTaskQueue(fetch_maxsize=1, process_maxsize=1)
    # Don't start workers so queue fills up
    q._fetch_queue = asyncio.Queue(maxsize=1)
    q._fetch_queue.put_nowait(("source-x", False))  # fill it
    result = await q.enqueue_fetch("source-overflow")
    assert result is False


@pytest.mark.asyncio
async def test_enqueue_process_returns_true_when_capacity_available():
    from app.tasks.task_queue import BoundedTaskQueue
    q = BoundedTaskQueue(fetch_maxsize=5, process_maxsize=5)
    await q.start_workers(fetch_workers=1, process_workers=1)
    try:
        with patch("app.tasks.process_tasks.process_new_content", new=AsyncMock()):
            result = await q.enqueue_process("content-1")
        assert result is True
    finally:
        await q.stop_workers()


@pytest.mark.asyncio
async def test_stop_workers_is_idempotent():
    from app.tasks.task_queue import BoundedTaskQueue
    q = BoundedTaskQueue()
    await q.start_workers()
    await q.stop_workers()
    await q.stop_workers()  # 第二次调用不应报错
