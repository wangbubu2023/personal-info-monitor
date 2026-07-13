"""Bounded async task queue for fetch and process jobs.

Replaces scattered asyncio.create_task() calls with a queue-backed worker pool,
providing back-pressure: when the queue is full, new tasks are dropped (logged)
instead of being silently heap-allocated.

Phase 5 step 9 of the module refactor removed the worker class's direct
imports of ``app.tasks.fetch_tasks.fetch_source`` and
``app.domains.ingest.finish.finish_content``: the platform layer must not
depend on business domains. Handler callables are now passed into
:meth:`BoundedTaskQueue.start_workers` by the application bootstrap
(``app.main``) — the same arrangement standard worker frameworks like
RQ / Celery / Arq use.
"""

import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Awaitable, Callable, Optional

from app.platform.observability.logger import get_logger
from app.platform.observability.metrics import task_queue_metrics

FetchHandler = Callable[[str, bool], Awaitable[None]]
"""``(source_id, manual_trigger) -> awaitable`` — runs a single fetch job."""

ProcessHandler = Callable[[str, Optional[str]], Awaitable[None]]
"""``(content_id, job_id) -> awaitable`` — runs a single bounded process job."""

LISTING_TRANSLATION_JOB_ID = "listing-translation"

logger = get_logger(__name__)

_dlq_logger: logging.Logger | None = None


def _dropped_task_logger() -> logging.Logger:
    global _dlq_logger
    if _dlq_logger is not None:
        return _dlq_logger
    from app.platform.config.settings import get_settings

    settings = get_settings()
    log_path = os.path.join(settings.data_dir, "dropped_tasks.log")
    lg = logging.getLogger("pim.taskqueue.dlq")
    lg.setLevel(logging.INFO)
    lg.handlers.clear()
    handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    lg.addHandler(handler)
    lg.propagate = False
    _dlq_logger = lg
    return lg


class BoundedTaskQueue:
    def __init__(self, fetch_maxsize: int = 200, process_maxsize: int = 200):
        self._fetch_maxsize = fetch_maxsize
        self._process_maxsize = process_maxsize
        self._fetch_queue: asyncio.Queue = asyncio.Queue(maxsize=fetch_maxsize)
        self._process_queue: asyncio.Queue = asyncio.Queue(maxsize=process_maxsize)
        self._workers: list[asyncio.Task] = []
        self._fetch_handler: Optional[FetchHandler] = None
        self._process_handler: Optional[ProcessHandler] = None

    def _record_dropped_task(self, task_type: str, item_id: str, details: str = ""):
        """Record dropped task to a rotating DLQ log under ``data_dir``."""
        import datetime

        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            _dropped_task_logger().info("[%s] DROPPED %s: %s | %s", ts, task_type, item_id, details)
        except Exception:
            logger.error("Failed to write dropped-task DLQ log", exc_info=True)

    async def enqueue_fetch(self, source_id: str, manual_trigger: bool = False) -> bool:
        """Enqueue a fetch job. Returns False (and logs) if queue is full."""
        try:
            self._fetch_queue.put_nowait((source_id, manual_trigger))
            return True
        except asyncio.QueueFull:
            logger.warning(
                "fetch queue full (maxsize=%d), dropping source_id=%s",
                self._fetch_maxsize, source_id,
            )
            self._record_dropped_task("FETCH", source_id, f"manual={manual_trigger}")
            task_queue_metrics.record_dropped("fetch")
            return False

    async def enqueue_ingest_finish(self, content_id: str, job_id: str | None = None) -> bool:
        """Enqueue an ingest-finalization job (LLM-free post-fetch enrichment).

        The SQLite job table is the durable truth source; the bounded asyncio
        queue is only the in-process execution cache. A full cache can delay a
        job, but must not be able to lose it permanently.
        """
        from app.platform.workers.postprocess_jobs import ensure_postprocess_job

        await asyncio.to_thread(ensure_postprocess_job, content_id, job_id)
        try:
            self._process_queue.put_nowait((content_id, job_id))
            return True
        except asyncio.QueueFull:
            logger.warning(
                "process queue full (maxsize=%d), deferring durable content_id=%s",
                self._process_maxsize, content_id,
            )
            self._record_dropped_task("PROCESS", content_id, f"job_id={job_id}; durable=pending")
            task_queue_metrics.record_dropped("process")
            return False

    async def enqueue_ingest_finish_many(
        self,
        content_ids: list[str],
        job_id: str | None = None,
    ) -> int:
        """Persist a source batch once, then populate the execution cache.

        The durable table remains the truth source when the bounded in-memory
        queue fills up. The return value is the number immediately cached;
        every valid ID is durable regardless of that number.
        """
        from app.platform.workers.postprocess_jobs import ensure_postprocess_jobs

        unique_ids: list[str] = []
        seen: set[str] = set()
        for raw_content_id in content_ids:
            content_id = str(raw_content_id or "").strip()
            if not content_id or content_id in seen:
                continue
            seen.add(content_id)
            unique_ids.append(content_id)
        if not unique_ids:
            return 0
        await asyncio.to_thread(
            ensure_postprocess_jobs,
            [(content_id, job_id) for content_id in unique_ids],
        )

        enqueued = 0
        for content_id in unique_ids:
            try:
                self._process_queue.put_nowait((content_id, job_id))
                enqueued += 1
            except asyncio.QueueFull:
                logger.warning(
                    "process queue full (maxsize=%d), deferring durable content_id=%s",
                    self._process_maxsize,
                    content_id,
                )
                self._record_dropped_task(
                    "PROCESS",
                    content_id,
                    f"job_id={job_id}; durable=pending",
                )
                task_queue_metrics.record_dropped("process")
        return enqueued

    async def enqueue_listing_translation(self, content_id: str) -> bool:
        """Enqueue a bounded listing translation sidecar job."""
        return await self.enqueue_ingest_finish(content_id, job_id=LISTING_TRANSLATION_JOB_ID)

    async def start_workers(
        self,
        fetch_workers: int = 4,
        process_workers: int = 4,
        *,
        fetch_handler: Optional[FetchHandler] = None,
        process_handler: Optional[ProcessHandler] = None,
    ) -> None:
        """Start worker coroutines. Call once from app lifespan startup.

        ``fetch_handler`` and ``process_handler`` are required for the
        worker coroutines to do anything meaningful, but are kept
        optional so the existing ``test_task_queue.py::test_stop_workers_is_idempotent``
        (which just exercises start/stop lifecycle) keeps working.
        When a handler is ``None``, the corresponding worker drains
        the queue but performs no work — useful for unit tests that
        only need the queue surface, not real fetch / finish behaviour.
        """
        if fetch_handler is not None and fetch_workers < 1:
            raise ValueError("fetch_workers must be at least 1 when a fetch handler is configured")
        self._fetch_handler = fetch_handler
        self._process_handler = process_handler
        for _ in range(fetch_workers):
            self._workers.append(asyncio.create_task(self._fetch_worker()))
        for _ in range(process_workers):
            self._workers.append(asyncio.create_task(self._process_worker()))
        logger.info("BoundedTaskQueue started: %d fetch workers, %d process workers",
                    fetch_workers, process_workers)

    async def stop_workers(self) -> None:
        """Drain queues and cancel workers. Call from app lifespan shutdown."""
        for w in self._workers:
            w.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("BoundedTaskQueue stopped")

    async def _fetch_worker(self) -> None:
        while True:
            try:
                source_id, manual_trigger = await self._fetch_queue.get()
                try:
                    if self._fetch_handler is not None:
                        await self._fetch_handler(source_id, manual_trigger)
                except Exception:
                    logger.exception("fetch worker error for source_id=%s", source_id)
                finally:
                    self._fetch_queue.task_done()
                    # Explicitly hand control back to request handlers before
                    # this worker immediately claims another queued source.
                    await asyncio.sleep(0)
            except asyncio.CancelledError:
                break

    async def _process_worker(self) -> None:
        from app.platform.workers.postprocess_jobs import (
            claim_postprocess_job,
            mark_postprocess_job_failed,
            mark_postprocess_job_succeeded,
        )

        while True:
            try:
                content_id, job_id = await self._process_queue.get()
                try:
                    claimed = await asyncio.to_thread(claim_postprocess_job, content_id, job_id)
                    if not claimed:
                        continue
                    if self._process_handler is not None:
                        await self._process_handler(content_id, job_id)
                    await asyncio.to_thread(mark_postprocess_job_succeeded, content_id, job_id)
                except Exception as exc:
                    status = await asyncio.to_thread(mark_postprocess_job_failed, content_id, job_id, exc)
                    logger.exception("process worker error for content_id=%s status=%s", content_id, status)
                finally:
                    self._process_queue.task_done()
            except asyncio.CancelledError:
                break


# Module-level singleton used by fetch_tasks and process_tasks
task_queue = BoundedTaskQueue()
