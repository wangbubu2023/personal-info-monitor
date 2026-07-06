# backend/tests/test_task_queue.py
import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


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
async def test_enqueue_ingest_finish_returns_true_when_capacity_available():
    from app.tasks.task_queue import BoundedTaskQueue
    q = BoundedTaskQueue(fetch_maxsize=5, process_maxsize=5)
    result = await q.enqueue_ingest_finish("content-1")
    assert result is True


@pytest.mark.asyncio
async def test_enqueue_listing_translation_uses_process_queue_job_id():
    from app.tasks.task_queue import BoundedTaskQueue, LISTING_TRANSLATION_JOB_ID

    q = BoundedTaskQueue(fetch_maxsize=5, process_maxsize=5)

    result = await q.enqueue_listing_translation("content-1")

    assert result is True
    assert q._process_queue.get_nowait() == ("content-1", LISTING_TRANSLATION_JOB_ID)


@pytest.mark.asyncio
async def test_stop_workers_is_idempotent():
    from app.tasks.task_queue import BoundedTaskQueue
    q = BoundedTaskQueue()
    await q.start_workers()
    await q.stop_workers()
    await q.stop_workers()  # 第二次调用不应报错


@pytest.mark.asyncio
async def test_startup_refinish_requeues_recent_unfinished_content():
    from app.platform.runtime.lifespan import enqueue_unfinished_content_on_startup

    rows = [
        SimpleNamespace(id="needs-finish", metadata_={}),
        SimpleNamespace(id="done", metadata_={"fetch_acceptance": "accepted"}),
    ]
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = rows

    with patch("app.database.SessionLocal", return_value=db):
        with patch("app.tasks.task_queue.task_queue.enqueue_ingest_finish", new=AsyncMock(return_value=True)) as enqueue:
            count = await enqueue_unfinished_content_on_startup()

    assert count == 1
    enqueue.assert_awaited_once_with("needs-finish", job_id="startup-refinish")
