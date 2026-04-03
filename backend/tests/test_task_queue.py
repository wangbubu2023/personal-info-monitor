# backend/tests/test_task_queue.py
import asyncio
import pytest


@pytest.mark.asyncio
async def test_enqueue_fetch_returns_true_when_capacity_available():
    from app.tasks.task_queue import BoundedTaskQueue
    q = BoundedTaskQueue(fetch_maxsize=5, process_maxsize=5)
    # No workers needed — just test the return value when queue has space
    result = await q.enqueue_fetch("source-1")
    assert result is True


@pytest.mark.asyncio
async def test_enqueue_fetch_returns_false_when_queue_full():
    from app.tasks.task_queue import BoundedTaskQueue
    q = BoundedTaskQueue(fetch_maxsize=1, process_maxsize=1)
    # Don't start workers so queue fills up
    q._fetch_queue.put_nowait(("source-x", False))  # fill it
    result = await q.enqueue_fetch("source-overflow")
    assert result is False


@pytest.mark.asyncio
async def test_enqueue_process_returns_true_when_capacity_available():
    from app.tasks.task_queue import BoundedTaskQueue
    q = BoundedTaskQueue(fetch_maxsize=5, process_maxsize=5)
    result = await q.enqueue_process("content-1")
    assert result is True


@pytest.mark.asyncio
async def test_stop_workers_is_idempotent():
    from app.tasks.task_queue import BoundedTaskQueue
    q = BoundedTaskQueue()
    await q.start_workers()
    await q.stop_workers()
    await q.stop_workers()  # 第二次调用不应报错
