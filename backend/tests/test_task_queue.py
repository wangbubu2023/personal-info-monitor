# backend/tests/test_task_queue.py
import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch


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
    with patch("app.platform.workers.postprocess_jobs.ensure_postprocess_job") as ensure:
        result = await q.enqueue_ingest_finish("content-1")
    assert result is True
    ensure.assert_called_once_with("content-1", None)


@pytest.mark.asyncio
async def test_enqueue_ingest_finish_persists_even_when_process_queue_full():
    from app.tasks.task_queue import BoundedTaskQueue

    q = BoundedTaskQueue(fetch_maxsize=1, process_maxsize=1)
    q._process_queue.put_nowait(("content-x", None))

    with patch("app.platform.workers.postprocess_jobs.ensure_postprocess_job") as ensure:
        result = await q.enqueue_ingest_finish("content-overflow", job_id="fetch-1")

    assert result is False
    ensure.assert_called_once_with("content-overflow", "fetch-1")


@pytest.mark.asyncio
async def test_enqueue_ingest_finish_many_persists_source_batch_once():
    from app.tasks.task_queue import BoundedTaskQueue

    q = BoundedTaskQueue(fetch_maxsize=5, process_maxsize=25)
    content_ids = [f"content-{index}" for index in range(20)]

    with patch("app.platform.workers.postprocess_jobs.ensure_postprocess_jobs") as ensure:
        enqueued = await q.enqueue_ingest_finish_many(content_ids, job_id="fetch-1")

    assert enqueued == 20
    ensure.assert_called_once_with([(content_id, "fetch-1") for content_id in content_ids])
    assert q._process_queue.qsize() == 20


@pytest.mark.asyncio
async def test_enqueue_listing_translation_uses_process_queue_job_id():
    from app.tasks.task_queue import BoundedTaskQueue, LISTING_TRANSLATION_JOB_ID

    q = BoundedTaskQueue(fetch_maxsize=5, process_maxsize=5)

    with patch("app.platform.workers.postprocess_jobs.ensure_postprocess_job") as ensure:
        result = await q.enqueue_listing_translation("content-1")

    assert result is True
    assert q._process_queue.get_nowait() == ("content-1", LISTING_TRANSLATION_JOB_ID)
    ensure.assert_called_once_with("content-1", LISTING_TRANSLATION_JOB_ID)


@pytest.mark.asyncio
async def test_stop_workers_is_idempotent():
    from app.tasks.task_queue import BoundedTaskQueue
    q = BoundedTaskQueue()
    await q.start_workers()
    await q.stop_workers()
    await q.stop_workers()  # 第二次调用不应报错


@pytest.mark.asyncio
async def test_start_workers_rejects_zero_fetch_workers_with_fetch_handler():
    from app.tasks.task_queue import BoundedTaskQueue

    q = BoundedTaskQueue()
    with pytest.raises(ValueError, match="fetch_workers must be at least 1"):
        await q.start_workers(fetch_workers=0, fetch_handler=AsyncMock())


@pytest.mark.asyncio
async def test_process_worker_marks_success_and_failure():
    from app.tasks.task_queue import BoundedTaskQueue

    q = BoundedTaskQueue(fetch_maxsize=5, process_maxsize=5)
    handler = AsyncMock(side_effect=[None, RuntimeError("boom")])

    with patch("app.platform.workers.postprocess_jobs.claim_postprocess_job", return_value=True) as claim:
        with patch("app.platform.workers.postprocess_jobs.mark_postprocess_job_succeeded") as succeeded:
            with patch("app.platform.workers.postprocess_jobs.mark_postprocess_job_failed", return_value="pending") as failed:
                await q.start_workers(fetch_workers=0, process_workers=1, process_handler=handler)
                q._process_queue.put_nowait(("ok", None))
                q._process_queue.put_nowait(("bad", None))
                await asyncio.wait_for(q._process_queue.join(), timeout=2)
                await q.stop_workers()

    assert claim.call_count == 2
    succeeded.assert_called_once_with("ok", None)
    failed.assert_called_once_with("bad", None, ANY)


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
        with patch(
            "app.tasks.task_queue.task_queue.enqueue_ingest_finish_many",
            new=AsyncMock(return_value=1),
        ) as enqueue:
            count = await enqueue_unfinished_content_on_startup()

    assert count == 1
    enqueue.assert_awaited_once_with(["needs-finish"], job_id="startup-refinish")
