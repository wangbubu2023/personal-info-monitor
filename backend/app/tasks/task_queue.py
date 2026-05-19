"""Bounded async task queue for fetch and process jobs.

Replaces scattered asyncio.create_task() calls with a queue-backed worker pool,
providing back-pressure: when the queue is full, new tasks are dropped (logged)
instead of being silently heap-allocated.
"""

import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler

from app.utils.logger import get_logger
from app.utils.metrics import task_queue_metrics

logger = get_logger(__name__)

_dlq_logger: logging.Logger | None = None


def _dropped_task_logger() -> logging.Logger:
    global _dlq_logger
    if _dlq_logger is not None:
        return _dlq_logger
    from app.config import get_settings

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

        Renamed from ``enqueue_process`` in Phase 3 step 5 of the
        module-refactor blueprint to match the ``ingest.finish_content``
        target it dispatches to. The legacy ``enqueue_process`` name is
        kept as a thin alias below (Phase 7 will retire it).
        """
        try:
            self._process_queue.put_nowait((content_id, job_id))
            return True
        except asyncio.QueueFull:
            logger.warning(
                "process queue full (maxsize=%d), dropping content_id=%s",
                self._process_maxsize, content_id,
            )
            self._record_dropped_task("PROCESS", content_id, f"job_id={job_id}")
            task_queue_metrics.record_dropped("process")
            return False

    async def enqueue_process(self, content_id: str, job_id: str | None = None) -> bool:
        """Deprecated alias for :meth:`enqueue_ingest_finish`.

        .. deprecated::
           Use :meth:`enqueue_ingest_finish` instead. This alias keeps
           legacy callers (and the matching ``test_task_queue.py``
           assertions) working through Phase 7.
        """
        return await self.enqueue_ingest_finish(content_id, job_id=job_id)

    async def start_workers(self, fetch_workers: int = 4, process_workers: int = 4) -> None:
        """Start worker coroutines. Call once from app lifespan startup."""
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
        from app.tasks.fetch_tasks import fetch_source
        while True:
            try:
                source_id, manual_trigger = await self._fetch_queue.get()
                try:
                    await fetch_source(source_id, manual_trigger=manual_trigger)
                except Exception:
                    logger.exception("fetch worker error for source_id=%s", source_id)
                finally:
                    self._fetch_queue.task_done()
            except asyncio.CancelledError:
                break

    async def _process_worker(self) -> None:
        from app.domains.ingest.finish import finish_content
        while True:
            try:
                content_id, job_id = await self._process_queue.get()
                try:
                    await finish_content(content_id, job_id=job_id)
                except Exception:
                    logger.exception("process worker error for content_id=%s", content_id)
                finally:
                    self._process_queue.task_done()
            except asyncio.CancelledError:
                break


# Module-level singleton used by fetch_tasks and process_tasks
task_queue = BoundedTaskQueue()
