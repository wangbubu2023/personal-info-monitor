"""Bounded async task queue for fetch and process jobs.

Replaces scattered asyncio.create_task() calls with a queue-backed worker pool,
providing back-pressure: when the queue is full, new tasks are dropped (logged)
instead of being silently heap-allocated.
"""

import asyncio
from app.utils.logger import get_logger

logger = get_logger(__name__)


class BoundedTaskQueue:
    def __init__(self, fetch_maxsize: int = 200, process_maxsize: int = 200):
        self._fetch_maxsize = fetch_maxsize
        self._process_maxsize = process_maxsize
        self._fetch_queue: asyncio.Queue = asyncio.Queue(maxsize=fetch_maxsize)
        self._process_queue: asyncio.Queue = asyncio.Queue(maxsize=process_maxsize)
        self._workers: list[asyncio.Task] = []

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
            return False

    async def enqueue_process(self, content_id: str) -> bool:
        """Enqueue a process job. Returns False (and logs) if queue is full."""
        try:
            self._process_queue.put_nowait(content_id)
            return True
        except asyncio.QueueFull:
            logger.warning(
                "process queue full (maxsize=%d), dropping content_id=%s",
                self._process_maxsize, content_id,
            )
            return False

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
        from app.tasks.process_tasks import process_new_content
        while True:
            try:
                content_id = await self._process_queue.get()
                try:
                    await process_new_content(content_id)
                except Exception:
                    logger.exception("process worker error for content_id=%s", content_id)
                finally:
                    self._process_queue.task_done()
            except asyncio.CancelledError:
                break


# Module-level singleton used by fetch_tasks and process_tasks
task_queue = BoundedTaskQueue()
