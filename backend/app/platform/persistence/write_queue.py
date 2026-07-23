"""Priority write queue plus SQLite single-writer coordination."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
import itertools
from threading import Lock
from time import perf_counter
from typing import Any, Callable

from app.platform.observability.metrics import reliability_metrics


class WriteQueueFull(RuntimeError):
    pass


class SQLiteWriteCoordinator:
    """Process-wide writer mutex used by ORM session hooks."""

    def __init__(self) -> None:
        self._lock = Lock()

    def acquire(self) -> float:
        started = perf_counter()
        self._lock.acquire()
        wait_ms = (perf_counter() - started) * 1000
        reliability_metrics.record("sqlite_lock_wait_ms", wait_ms)
        return perf_counter()

    def release(self, transaction_started: float) -> None:
        reliability_metrics.record(
            "sqlite_transaction_duration_ms",
            (perf_counter() - transaction_started) * 1000,
        )
        self._lock.release()

    @contextmanager
    def write(self):
        started = self.acquire()
        try:
            yield
        finally:
            self.release(started)


sqlite_write_coordinator = SQLiteWriteCoordinator()


@dataclass(order=True)
class _QueuedWrite:
    priority: int
    sequence: int
    submitted_at: float
    callback: Callable[[], Any] = field(compare=False)
    future: asyncio.Future = field(compare=False)


class AsyncWriteQueue:
    """Bounded priority queue for explicit batched persistence commands."""

    def __init__(self, *, maxsize: int = 1000, batch_size: int = 50) -> None:
        self._queue: asyncio.PriorityQueue[_QueuedWrite] = asyncio.PriorityQueue(maxsize=maxsize)
        self._batch_size = max(1, int(batch_size))
        self._sequence = itertools.count()
        self._worker: asyncio.Task | None = None
        self._accepting = False

    async def start(self) -> None:
        if self._worker is not None and not self._worker.done():
            return
        self._accepting = True
        self._worker = asyncio.create_task(self._run(), name="pim-sqlite-write-queue")

    async def submit(
        self,
        callback: Callable[[], Any],
        *,
        priority: int = 100,
        timeout: float = 5.0,
    ) -> Any:
        if not self._accepting:
            raise RuntimeError("write queue is not accepting commands")
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        item = _QueuedWrite(
            int(priority),
            next(self._sequence),
            loop.time(),
            callback,
            future,
        )
        try:
            await asyncio.wait_for(self._queue.put(item), timeout=max(0.01, float(timeout)))
        except asyncio.TimeoutError as exc:
            reliability_metrics.record("write_queue_backpressure")
            raise WriteQueueFull("write queue admission timed out") from exc
        return await future

    async def drain(self, *, timeout: float = 30.0) -> bool:
        self._accepting = False
        try:
            await asyncio.wait_for(self._queue.join(), timeout=max(0.01, float(timeout)))
            drained = True
        except asyncio.TimeoutError:
            drained = False
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
            self._worker = None
        return drained

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            first = await self._queue.get()
            batch = [first]
            while len(batch) < self._batch_size:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            reliability_metrics.record("write_queue_batch_size", len(batch))
            for item in batch:
                reliability_metrics.record(
                    "write_queue_age_ms",
                    (loop.time() - item.submitted_at) * 1000,
                )
                try:
                    result = await asyncio.to_thread(item.callback)
                except Exception as exc:  # noqa: BLE001 - propagate command failure to submitter
                    if not item.future.done():
                        item.future.set_exception(exc)
                else:
                    if not item.future.done():
                        item.future.set_result(result)
                finally:
                    self._queue.task_done()


write_queue = AsyncWriteQueue()

__all__ = [
    "AsyncWriteQueue",
    "SQLiteWriteCoordinator",
    "WriteQueueFull",
    "sqlite_write_coordinator",
    "write_queue",
]
