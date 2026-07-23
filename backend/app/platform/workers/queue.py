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
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Awaitable, Callable, Optional

from app.platform.observability.logger import get_logger
from app.platform.observability.metrics import task_queue_metrics
from app.utils.datetime import utcnow_naive

FetchHandler = Callable[[str, bool, str], Awaitable[object]]
"""``(source_id, manual_trigger, fetch_job_id) -> awaitable``."""

ProcessHandler = Callable[[str, Optional[str]], Awaitable[None]]
"""``(content_id, job_id) -> awaitable`` — runs a single bounded process job."""

LISTING_TRANSLATION_JOB_ID = "listing-translation"

logger = get_logger(__name__)

_dlq_logger: logging.Logger | None = None


@dataclass(frozen=True)
class ShutdownSummary:
    duration_ms: int
    completed: int
    abandoned: int
    cancelled: int
    timed_out: bool


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
        self._accepting = True
        self._stopping = False
        self._completed_during_shutdown = 0
        self._abandoned_during_shutdown = 0
        self._cancelled_during_shutdown = 0
        self._in_flight: dict[asyncio.Task, tuple[str, tuple]] = {}
        self._last_shutdown_summary: ShutdownSummary | None = None

    @property
    def accepting(self) -> bool:
        return self._accepting and not self._stopping

    @property
    def last_shutdown_summary(self) -> ShutdownSummary | None:
        return self._last_shutdown_summary

    def _record_dropped_task(self, task_type: str, item_id: str, details: str = ""):
        """Record dropped task to a rotating DLQ log under ``data_dir``."""
        import datetime

        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            _dropped_task_logger().info("[%s] DROPPED %s: %s | %s", ts, task_type, item_id, details)
        except Exception:
            logger.error("Failed to write dropped-task DLQ log", exc_info=True)

    async def enqueue_fetch(
        self,
        source_id: str,
        manual_trigger: bool = False,
        *,
        fetch_kind: str | None = None,
        due_window: datetime | None = None,
        not_before: datetime | None = None,
    ):
        """Persist a FetchJob first, then best-effort cache it for execution."""
        from app.platform.workers.fetch_jobs import FetchDispatchResult, create_fetch_job

        kind = fetch_kind or ("manual" if manual_trigger else "scheduled")
        try:
            result = await asyncio.to_thread(
                create_fetch_job,
                source_id,
                fetch_kind=kind,
                due_window=due_window,
                not_before=not_before,
            )
        except Exception as exc:  # noqa: BLE001 - API must report rejected truthfully
            logger.exception("fetch job persistence failed for source_id=%s", source_id)
            return FetchDispatchResult(
                source_id=str(source_id),
                fetch_kind=kind,
                job_id=None,
                business_key="",
                persisted=False,
                rejected=True,
                state="rejected",
                reason=str(exc)[:500],
            )
        if result.duplicate or not result.job_id:
            return result
        if not_before is not None and not_before > utcnow_naive():
            return result
        if not self.accepting:
            return FetchDispatchResult(
                source_id=result.source_id,
                fetch_kind=result.fetch_kind,
                job_id=result.job_id,
                business_key=result.business_key,
                persisted=True,
                state=result.state,
                reason="dispatcher_stopping",
            )
        enqueued = await self.enqueue_existing_fetch(result.job_id, str(source_id), manual_trigger)
        return FetchDispatchResult(
            source_id=result.source_id,
            fetch_kind=result.fetch_kind,
            job_id=result.job_id,
            business_key=result.business_key,
            persisted=result.persisted,
            enqueued=enqueued,
            duplicate=result.duplicate,
            rejected=result.rejected,
            state=result.state,
            reason=None if enqueued else "execution_cache_full",
        )

    async def enqueue_existing_fetch(self, job_id: str, source_id: str, manual_trigger: bool = False) -> bool:
        """Cache an already-durable pending FetchJob without creating another row."""
        from app.platform.workers.fetch_jobs import mark_fetch_job_enqueued

        if not self.accepting:
            return False
        try:
            self._fetch_queue.put_nowait((job_id, source_id, manual_trigger))
            await asyncio.to_thread(mark_fetch_job_enqueued, job_id)
            return True
        except asyncio.QueueFull:
            logger.warning(
                "fetch queue full (maxsize=%d), deferring durable source_id=%s job_id=%s",
                self._fetch_maxsize, source_id,
                job_id,
            )
            self._record_dropped_task("FETCH", source_id, f"manual={manual_trigger}; durable=pending; job_id={job_id}")
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
        if not self.accepting:
            return False
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
        if not self.accepting:
            return 0

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
        self._accepting = True
        self._stopping = False
        self._fetch_handler = fetch_handler
        self._process_handler = process_handler
        for _ in range(fetch_workers):
            self._workers.append(asyncio.create_task(self._fetch_worker()))
        for _ in range(process_workers):
            self._workers.append(asyncio.create_task(self._process_worker()))
        logger.info("BoundedTaskQueue started: %d fetch workers, %d process workers",
                    fetch_workers, process_workers)

    async def stop_workers(self, grace_timeout: float | None = None) -> ShutdownSummary:
        """Stop leasing, drain queued/in-flight work, then fence timed-out jobs."""
        loop = asyncio.get_running_loop()
        started = loop.time()
        self._accepting = False
        self._stopping = True
        self._completed_during_shutdown = 0
        self._abandoned_during_shutdown = 0
        self._cancelled_during_shutdown = 0
        if grace_timeout is None:
            from app.platform.config.settings import get_settings

            grace_timeout = float(get_settings().shutdown_grace_seconds)
        timed_out = False
        try:
            await asyncio.wait_for(
                asyncio.gather(self._fetch_queue.join(), self._process_queue.join()),
                timeout=max(0.1, float(grace_timeout)),
            )
        except asyncio.TimeoutError:
            timed_out = True
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._stopping = False
        summary = ShutdownSummary(
            duration_ms=int((loop.time() - started) * 1000),
            completed=self._completed_during_shutdown,
            abandoned=self._abandoned_during_shutdown,
            cancelled=self._cancelled_during_shutdown,
            timed_out=timed_out,
        )
        self._last_shutdown_summary = summary
        logger.info(
            "BoundedTaskQueue stopped duration_ms=%d completed=%d abandoned=%d cancelled=%d timed_out=%s",
            summary.duration_ms,
            summary.completed,
            summary.abandoned,
            summary.cancelled,
            summary.timed_out,
        )
        return summary

    async def _heartbeat(
        self,
        callback,
        args: tuple,
        *,
        done: asyncio.Event,
        interval: float,
    ) -> None:
        while not done.is_set():
            try:
                await asyncio.wait_for(done.wait(), timeout=interval)
            except asyncio.TimeoutError:
                alive = await asyncio.to_thread(callback, *args)
                if not alive:
                    logger.warning("Job heartbeat lost CAS ownership")
                    return

    async def _fetch_worker(self) -> None:
        from app.platform.workers.fetch_jobs import (
            claim_fetch_job,
            heartbeat_fetch_job,
            mark_fetch_job_abandoned,
            mark_fetch_job_failed,
            mark_fetch_job_succeeded,
            take_claimed_fetch_lease,
        )

        while True:
            fetch_job_id = source_id = None
            lease = None
            current = None
            done = None
            heartbeat_task = None
            try:
                fetch_job_id, source_id, manual_trigger = await self._fetch_queue.get()
                current = asyncio.current_task()
                if current is not None:
                    self._in_flight[current] = ("fetch", (fetch_job_id, source_id))
                try:
                    claimed = await asyncio.to_thread(claim_fetch_job, fetch_job_id)
                    if not claimed:
                        continue
                    lease = take_claimed_fetch_lease(fetch_job_id)
                    from app.platform.config.settings import get_settings

                    settings = get_settings()
                    done = asyncio.Event()
                    heartbeat_task = None
                    if lease is not None:
                        heartbeat_task = asyncio.create_task(
                            self._heartbeat(
                                heartbeat_fetch_job,
                                (fetch_job_id, lease.owner, lease.token),
                                done=done,
                                interval=float(settings.job_heartbeat_seconds),
                            )
                        )
                    if self._fetch_handler is not None:
                        await asyncio.wait_for(
                            self._fetch_handler(source_id, manual_trigger, fetch_job_id),
                            timeout=float(settings.fetch_stage_timeout_seconds),
                        )
                    done.set()
                    if heartbeat_task is not None:
                        await heartbeat_task
                    kwargs = {"owner": lease.owner, "token": lease.token} if lease is not None else {}
                    committed = await asyncio.to_thread(mark_fetch_job_succeeded, fetch_job_id, **kwargs)
                    if not committed:
                        logger.warning("Fetch completion rejected by CAS job_id=%s", fetch_job_id)
                    elif self._stopping:
                        self._completed_during_shutdown += 1
                except asyncio.CancelledError:
                    if lease is not None:
                        abandoned = await asyncio.to_thread(
                            mark_fetch_job_abandoned,
                            fetch_job_id,
                            owner=lease.owner,
                            token=lease.token,
                            reason="shutdown_grace_expired",
                        )
                        self._abandoned_during_shutdown += int(abandoned)
                    self._cancelled_during_shutdown += 1
                    raise
                except Exception as exc:
                    kwargs = {"owner": lease.owner, "token": lease.token} if lease is not None else {}
                    status = await asyncio.to_thread(mark_fetch_job_failed, fetch_job_id, exc, **kwargs)
                    logger.exception(
                        "fetch worker error for source_id=%s job_id=%s status=%s",
                        source_id,
                        fetch_job_id,
                        status,
                    )
                finally:
                    if done is not None:
                        done.set()
                    if heartbeat_task is not None:
                        heartbeat_task.cancel()
                    self._fetch_queue.task_done()
                    if current is not None:
                        self._in_flight.pop(current, None)
                    # Explicitly hand control back to request handlers before
                    # this worker immediately claims another queued source.
                    await asyncio.sleep(0)
            except asyncio.CancelledError:
                break

    async def _process_worker(self) -> None:
        from app.platform.workers.postprocess_jobs import (
            claim_postprocess_job,
            heartbeat_postprocess_job,
            mark_postprocess_job_abandoned,
            mark_postprocess_job_failed,
            mark_postprocess_job_succeeded,
            take_claimed_postprocess_lease,
        )

        while True:
            content_id = job_id = None
            lease = None
            current = None
            done = None
            heartbeat_task = None
            try:
                content_id, job_id = await self._process_queue.get()
                current = asyncio.current_task()
                if current is not None:
                    self._in_flight[current] = ("postprocess", (content_id, job_id))
                try:
                    claimed = await asyncio.to_thread(claim_postprocess_job, content_id, job_id)
                    if not claimed:
                        continue
                    lease = take_claimed_postprocess_lease(content_id, job_id)
                    from app.platform.config.settings import get_settings

                    settings = get_settings()
                    done = asyncio.Event()
                    heartbeat_task = None
                    if lease is not None:
                        heartbeat_task = asyncio.create_task(
                            self._heartbeat(
                                heartbeat_postprocess_job,
                                (content_id, job_id, lease.owner, lease.token),
                                done=done,
                                interval=float(settings.job_heartbeat_seconds),
                            )
                        )
                    if self._process_handler is not None:
                        await asyncio.wait_for(
                            self._process_handler(content_id, job_id),
                            timeout=float(settings.postprocess_stage_timeout_seconds),
                        )
                    done.set()
                    if heartbeat_task is not None:
                        await heartbeat_task
                    kwargs = {"owner": lease.owner, "token": lease.token} if lease is not None else {}
                    committed = await asyncio.to_thread(
                        mark_postprocess_job_succeeded, content_id, job_id, **kwargs
                    )
                    if not committed:
                        logger.warning("Postprocess completion rejected by CAS content_id=%s", content_id)
                    elif self._stopping:
                        self._completed_during_shutdown += 1
                except asyncio.CancelledError:
                    if lease is not None:
                        abandoned = await asyncio.to_thread(
                            mark_postprocess_job_abandoned,
                            content_id,
                            job_id,
                            owner=lease.owner,
                            token=lease.token,
                            reason="shutdown_grace_expired",
                        )
                        self._abandoned_during_shutdown += int(abandoned)
                    self._cancelled_during_shutdown += 1
                    raise
                except Exception as exc:
                    kwargs = {"owner": lease.owner, "token": lease.token} if lease is not None else {}
                    status = await asyncio.to_thread(
                        mark_postprocess_job_failed, content_id, job_id, exc, **kwargs
                    )
                    logger.exception("process worker error for content_id=%s status=%s", content_id, status)
                finally:
                    if done is not None:
                        done.set()
                    if heartbeat_task is not None:
                        heartbeat_task.cancel()
                    self._process_queue.task_done()
                    if current is not None:
                        self._in_flight.pop(current, None)
            except asyncio.CancelledError:
                break


# Module-level singleton used by fetch_tasks and process_tasks
task_queue = BoundedTaskQueue()
