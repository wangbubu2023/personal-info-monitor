"""FastAPI application lifespan (startup / shutdown side effects).

Extracted from :mod:`app.main` in Phase 5 step 13. This module owns every
concrete runtime side-effect that happens around the request-serving
window:

* Optional ``PIM_SKIP_MIGRATIONS`` escape hatch + Alembic ``run_migrations``
  on startup.
* In-process metrics restore/persist around the lifespan boundary so
  ``rate()`` queries survive restarts.
* Scheduler bootstrap (``setup_scheduler``/``scheduler.start``/
  ``trigger_startup_jobs``) on startup; ``scheduler.shutdown`` on
  shutdown.
* Bounded task-queue worker bootstrap with dependency-injected fetch and
  process handlers (Phase 5 step 9 kept :mod:`app.platform.workers.queue`
  free of domain imports — the handlers themselves are passed in by the
  composition root in ``app.main`` so this module also stays out of
  ``app.domains``).
* Shared Playwright/Chromium pool shutdown before dropping the DB engine
  so we never leak a Chromium child on graceful reload.
* SSL-verify / feature-flag warnings surfaced via logs so operators
  notice unsafe defaults without needing to hit ``/api/system/doctor``.
* Friendly startup banner (API key mask, data dir, fetch concurrency,
  AI/ENRICH flag posture) printed to stdout for local operators.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from typing import Awaitable, Callable

from fastapi import FastAPI

from app.platform.config.settings import get_settings
from app.platform.config.settings import effective_fetch_concurrency
from app.platform.observability.logger import get_logger
from app.platform.observability.metrics import persist_metrics, restore_metrics
from app.platform.persistence.database import async_engine

logger = get_logger(__name__)

FetchHandler = Callable[[str, bool], Awaitable[None]]
ProcessHandler = Callable[[str, "str | None"], Awaitable[None]]


async def _watch_event_loop_lag(threshold_seconds: float, interval_seconds: float) -> None:
    """Log when the running event loop is stalled longer than the threshold."""
    loop = asyncio.get_running_loop()
    interval = max(0.1, interval_seconds)
    expected = loop.time() + interval
    while True:
        await asyncio.sleep(interval)
        now = loop.time()
        lag = now - expected
        if lag >= threshold_seconds:
            severe = lag >= max(threshold_seconds * 5, 5.0)
            log = logger.error if severe else logger.warning
            log(
                "Event loop lag %.3fs exceeded %.3fs threshold; check sync work in async paths%s",
                lag,
                threshold_seconds,
                " (severe stall)" if severe else "",
            )
        expected = now + interval


def _configure_event_loop_observability(settings) -> asyncio.Task | None:
    threshold = float(getattr(settings, "event_loop_slow_callback_seconds", 0) or 0)
    if threshold <= 0:
        return None

    loop = asyncio.get_running_loop()
    loop.slow_callback_duration = threshold
    if not loop.get_debug():
        loop.set_debug(True)

    interval = float(getattr(settings, "event_loop_lag_probe_interval_seconds", 1.0) or 1.0)
    logger.info(
        "Event loop slow-callback monitoring enabled (threshold=%.3fs, lag_probe_interval=%.3fs)",
        threshold,
        max(0.1, interval),
    )
    return loop.create_task(
        _watch_event_loop_lag(threshold, interval),
        name="pim-event-loop-lag-watch",
    )


async def enqueue_due_postprocess_jobs(*, limit: int = 200) -> int:
    """Refill the execution cache from durable pending postprocess jobs."""
    from app.platform.workers.postprocess_jobs import due_postprocess_jobs, recover_stale_postprocess_jobs
    from app.tasks.task_queue import task_queue

    recovered = await asyncio.to_thread(recover_stale_postprocess_jobs)
    if recovered:
        logger.warning("Recovered %d stale postprocess job(s)", recovered)
    jobs = await asyncio.to_thread(due_postprocess_jobs, limit=limit)
    enqueued = 0
    for content_id, job_id in jobs:
        try:
            task_queue._process_queue.put_nowait((content_id, job_id))
            enqueued += 1
        except asyncio.QueueFull:
            break
    if enqueued:
        logger.info("Queued %d durable postprocess jobs", enqueued)
    return enqueued


async def enqueue_unfinished_content_on_startup(
    *, limit: int = 200, lookback_hours: int = 24, job_id: str = "startup-refinish"
) -> int:
    """Requeue recent content that was stored before finish_content completed.

    Runs at startup *and* on a periodic schedule (see ``requeue_unfinished_content``):
    a bounded-queue drop or a worker crash mid-finish otherwise leaves content
    stuck in a half-processed state until the next restart, which for the
    long-running service install may be days away. The query is idempotent —
    items that already have ``fetch_acceptance`` recorded are skipped.
    """
    from app.database import SessionLocal
    from app.models import Content
    from app.tasks.task_queue import task_queue
    from app.utils.datetime import utcnow_naive

    cutoff = utcnow_naive() - timedelta(hours=lookback_hours)

    def _query_ids() -> list[str]:
        db = SessionLocal()
        try:
            rows = (
                db.query(Content)
                .filter(Content.fetched_at >= cutoff)
                .order_by(Content.fetched_at.desc())
                .limit(limit)
                .all()
            )
            ids: list[str] = []
            for content in rows:
                metadata = content.metadata_ if isinstance(content.metadata_, dict) else {}
                if metadata.get("fetch_acceptance") is None:
                    ids.append(str(content.id))
            return ids
        finally:
            db.close()

    ids = await asyncio.to_thread(_query_ids)
    enqueued = await task_queue.enqueue_ingest_finish_many(ids, job_id=job_id)
    if enqueued:
        logger.info("Requeued %d unfinished content items (%s)", enqueued, job_id)
    return enqueued


def _mask_secret(value: str, prefix: int = 4, suffix: int = 4) -> str:
    text = value or ""
    if not text:
        return "(not set)"
    if len(text) <= prefix + suffix:
        return "*" * len(text)
    return f"{text[:prefix]}...{text[-suffix:]}"


def build_lifespan(
    *,
    fetch_handler: FetchHandler,
    process_handler: ProcessHandler,
):
    """Return an ``asynccontextmanager`` wired with composition-root callbacks.

    ``fetch_handler`` / ``process_handler`` are supplied by ``app.main`` so the
    platform layer never imports ``app.domains.*`` directly — Phase 5's strict
    ``platform ↛ domains`` invariant stays clean.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = get_settings()
        event_loop_lag_task = None

        if os.environ.get("PIM_SKIP_MIGRATIONS", "").strip().lower() in {"1", "true", "yes", "on"}:
            logger.warning(
                "PIM_SKIP_MIGRATIONS is set — skipping Alembic migrations (development only; unsafe in production)"
            )
        else:
            from app.migrations import run_migrations

            await asyncio.to_thread(run_migrations)

        try:
            if restore_metrics():
                logger.info("Restored persisted metrics counters from data_dir checkpoint")
        except Exception as exc:  # noqa: BLE001 - observability best-effort
            logger.warning("Failed to restore metrics checkpoint: %s", exc)

        from app.scheduler import scheduler, setup_scheduler, trigger_startup_jobs

        setup_scheduler()
        scheduler.start()
        trigger_startup_jobs()

        from app.tasks.task_queue import task_queue

        active_fetches = effective_fetch_concurrency(settings)
        await task_queue.start_workers(
            fetch_workers=active_fetches,
            fetch_handler=fetch_handler,
            process_handler=process_handler,
        )
        await enqueue_due_postprocess_jobs()
        await enqueue_unfinished_content_on_startup()

        print(f"\n  PIM API Key: {_mask_secret(settings.pim_api_key)}")
        print(f"  Data dir:    {settings.data_dir}")
        print(
            "  Fetch concurrency: "
            f"{active_fetches} active (configured={settings.fetch_concurrency}, "
            f"safety_limit={settings.fetch_active_limit})"
        )
        if active_fetches < settings.fetch_concurrency:
            logger.warning(
                "Fetch concurrency emergency-capped at %d (configured=%d); "
                "raise FETCH_ACTIVE_LIMIT after the host is stable",
                active_fetches,
                settings.fetch_concurrency,
            )
        print(
            "  AI deployment hard-disable: "
            f"{'enabled' if settings.pim_ai_hard_disable else 'disabled'} "
            "(product policy: Settings -> AI models)"
        )
        print("  Bootstrap URL (web auto-provision): run `./pim bootstrap-url` to print")
        print()

        if settings.probe_disable_ssl_verify and settings.debug:
            logger.warning(
                "SECURITY WARNING: probe_disable_ssl_verify=True — SSL certificate verification is "
                "disabled for all outbound probe/fetch requests. This should never be enabled in "
                "production as it exposes the service to man-in-the-middle attacks."
            )
        elif settings.probe_disable_ssl_verify:
            logger.warning(
                "Ignoring probe_disable_ssl_verify because debug mode is disabled; outbound probe/fetch "
                "requests will continue to verify SSL certificates."
            )

        # Surface feature-flag posture so operators notice unsafe defaults in logs
        # without needing to hit /api/system/doctor first.
        from app.features import playwright_enabled, x_playwright_enabled

        if not playwright_enabled():
            logger.warning(
                "PIM_FEATURE_PLAYWRIGHT is disabled — JS-heavy site collection and "
                "cookie-login bootstrap will be skipped. Enable with PIM_FEATURE_PLAYWRIGHT=true."
            )
        else:
            logger.info("Playwright feature is enabled (PIM_FEATURE_PLAYWRIGHT=true).")
        if x_playwright_enabled():
            logger.warning(
                "PIM_FEATURE_X_PLAYWRIGHT=true — X (Twitter) logged-in Chromium hydration is active. "
                "This feature touches X Terms of Service grey area; keep it off unless "
                "you fully understand the risk."
            )

        try:
            event_loop_lag_task = _configure_event_loop_observability(settings)
            yield
        finally:
            if event_loop_lag_task is not None:
                event_loop_lag_task.cancel()
                with suppress(asyncio.CancelledError):
                    await event_loop_lag_task

            scheduler.shutdown(wait=False)
            await task_queue.stop_workers()

            # Release the shared Playwright/Chromium process before dropping the DB
            # engine so we never leak a Chromium child on graceful reload.
            try:
                from app.platform.browser.pool import shutdown_browser_pool

                await shutdown_browser_pool()
            except Exception as exc:  # noqa: BLE001 - shutdown best-effort
                logger.warning("Browser pool shutdown raised: %s", exc)

            try:
                if persist_metrics() is not None:
                    logger.info("Persisted metrics counters to data_dir checkpoint")
            except Exception as exc:  # noqa: BLE001 - observability best-effort
                logger.warning("Failed to persist metrics checkpoint: %s", exc)

            await async_engine.dispose()

    return lifespan
