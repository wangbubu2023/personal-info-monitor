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
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Awaitable, Callable

from fastapi import FastAPI

from app.platform.config.settings import get_settings
from app.platform.observability.logger import get_logger
from app.platform.observability.metrics import persist_metrics, restore_metrics
from app.platform.persistence.database import async_engine

logger = get_logger(__name__)

FetchHandler = Callable[[str, bool], Awaitable[None]]
ProcessHandler = Callable[[str, "str | None"], Awaitable[None]]


async def enqueue_unfinished_content_on_startup(*, limit: int = 200, lookback_hours: int = 24) -> int:
    """Requeue recent content that was stored before finish_content completed."""
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
    enqueued = 0
    for content_id in ids:
        if await task_queue.enqueue_ingest_finish(content_id, job_id="startup-refinish"):
            enqueued += 1
    if enqueued:
        logger.info("Requeued %d unfinished content items on startup", enqueued)
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

        await task_queue.start_workers(
            fetch_workers=settings.fetch_concurrency,
            fetch_handler=fetch_handler,
            process_handler=process_handler,
        )
        await enqueue_unfinished_content_on_startup()

        print(f"\n  PIM API Key: {_mask_secret(settings.pim_api_key)}")
        print(f"  Data dir:    {settings.data_dir}")
        print(f"  Fetch concurrency: {settings.fetch_concurrency}")
        _enrich_flags = (
            f"auto_on_ingest={settings.enrich_auto_on_ingest}, "
            f"summary={settings.enrich_summary_enabled}, "
            f"translate={settings.enrich_translate_enabled}"
        )
        print(
            "  AI processing: "
            f"{'enabled' if settings.ai_processing_enabled else 'disabled'} "
            f"(enrich: {_enrich_flags})"
        )
        print(
            "  Bootstrap URL (web auto-provision): run `./pim bootstrap-url` to print"
        )
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

        yield

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
