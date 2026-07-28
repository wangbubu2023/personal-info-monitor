"""APScheduler-based task scheduling replacing Celery Beat."""

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.platform.config.settings import get_settings
from app.utils.datetime import user_timezone
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

# Cron/interval jobs: avoid APScheduler defaults (misfire_grace_time=1s, coalesce=False)
# which silently skip runs after a >1s stall; keep overlapping runs from piling up.
_JOB_DEFAULTS = {
    "misfire_grace_time": 300,
    "coalesce": True,
    "max_instances": 1,
}

scheduler = AsyncIOScheduler(timezone=user_timezone())

# Hold strong references to fire-and-forget startup tasks. asyncio only keeps a
# weak reference to tasks created via ``loop.create_task``; without this the GC
# can collect a still-running task mid-flight.
_startup_tasks: set = set()


async def _run_durable(schedule_id: str, callback):
    from app.platform.workers.scheduler_ledger import execute_scheduled

    return await execute_scheduled(schedule_id, callback)


def _add_durable_job(callback, trigger, *, id: str, name: str) -> None:
    scheduler.add_job(
        _run_durable,
        trigger,
        args=(id, callback),
        id=id,
        name=name,
        replace_existing=True,
        **_JOB_DEFAULTS,
    )


def setup_scheduler():
    """Register all scheduled jobs."""
    from app.tasks.fetch_tasks import check_and_fetch_due_sources
    from app.domains.enrich.hourly.tasks import generate_previous_hour_digest
    from app.tasks.maintenance_tasks import (
        cleanup_old_content,
        cleanup_error_logs,
        purge_expired_runtime_locks,
        requeue_unfinished_content,
        dispatch_pending_fetch_jobs,
        dispatch_pending_postprocess_jobs,
        run_markdown_export,
    )
    from app.domains.enrich.notifications.daily_digest import send_daily_digest_emails
    from app.domains.enrich.notifications.doctor_digest import send_doctor_digest_email
    from app.domains.system.weekly_report import send_weekly_health_report_email
    from app.domains.events.lifecycle import run_lifecycle_tick
    from app.domains.events.rebalance import (
        cleanup_event_assignment_logs,
        run_event_rebalance_deep,
        run_event_rebalance_light,
    )

    # Core: check sources every 5 minutes (fetch priority)
    _add_durable_job(
        check_and_fetch_due_sources,
        IntervalTrigger(minutes=5),
        id="check_and_fetch_due_sources",
        name="Check and fetch due sources",
    )

    # Digest should always be registered when the feature is visible in the UI.
    # Run at minute 10 so fetch/finalize jobs have time to finish the previous
    # completed hour before the briefing is generated.
    _add_durable_job(
        generate_previous_hour_digest,
        CronTrigger(minute=10),
        id="generate_hourly_digest",
        name="Generate hourly briefing",
    )

    _add_durable_job(
        send_daily_digest_emails,
        CronTrigger(hour=8, minute=0),
        id="send_daily_digest_emails",
        name="Send daily digest emails",
    )

    # Daily DoctorService digest — silent on green, alert on degraded/error.
    # Runs a few minutes after the digest email so operators get one
    # combined morning triage.
    _add_durable_job(
        send_doctor_digest_email,
        CronTrigger(hour=8, minute=5),
        id="send_doctor_digest_email",
        name="Daily PIM doctor digest (alerts only)",
    )

    # Weekly operator health report (Monday morning, after daily/doctor
    # emails). Always sends when SMTP is configured — trend metrics that
    # never reach a push channel do not get looked at.
    _add_durable_job(
        send_weekly_health_report_email,
        CronTrigger(day_of_week="mon", hour=8, minute=10),
        id="send_weekly_health_report_email",
        name="Weekly PIM health report email",
    )

    # Maintenance: weekly cleanup (Sunday 3am)
    _add_durable_job(
        cleanup_old_content,
        CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="cleanup_old_content",
        name="Weekly content cleanup",
    )

    # Maintenance: reset error counts for recovered sources
    _add_durable_job(
        cleanup_error_logs,
        CronTrigger(hour="*/6", minute=30),
        id="cleanup_error_logs",
        name="Reset recovered source error counts",
    )

    _add_durable_job(
        purge_expired_runtime_locks,
        CronTrigger(minute=15),
        id="purge_expired_runtime_locks",
        name="Purge expired runtime fetch locks",
    )

    # Self-heal content stuck mid-finish (queue drops / worker crashes). The
    # same recovery runs at startup; this covers the long-running service that
    # may not restart for days.
    _add_durable_job(
        requeue_unfinished_content,
        IntervalTrigger(hours=6),
        id="requeue_unfinished_content",
        name="Requeue unfinished content",
    )

    _add_durable_job(
        dispatch_pending_fetch_jobs,
        IntervalTrigger(minutes=1),
        id="dispatch_pending_fetch_jobs",
        name="Dispatch durable pending fetch jobs",
    )

    _add_durable_job(
        dispatch_pending_postprocess_jobs,
        IntervalTrigger(seconds=30),
        id="dispatch_pending_postprocess_jobs",
        name="Dispatch durable pending postprocess jobs",
    )

    _add_durable_job(
        run_markdown_export,
        CronTrigger(minute=30),  # 每小时 30 分执行
        id="markdown_export",
        name="Incremental markdown export",
    )

    from app.platform.notifications.outbox import dispatch_pending_outbox

    _add_durable_job(
        dispatch_pending_outbox,
        IntervalTrigger(minutes=1),
        id="dispatch_notification_outbox",
        name="Dispatch durable notification outbox",
    )

    _add_durable_job(
        run_lifecycle_tick,
        CronTrigger(minute=20),
        id="event_lifecycle_tick",
        name="Event v1 lifecycle tick",
    )
    _add_durable_job(
        run_event_rebalance_light,
        CronTrigger(minute=25),
        id="event_rebalance_light",
        name="Event v1 light rebalance",
    )
    _add_durable_job(
        run_event_rebalance_deep,
        CronTrigger(hour=2, minute=20),
        id="event_rebalance_deep",
        name="Event v1 bounded deep rebalance",
    )
    _add_durable_job(
        cleanup_event_assignment_logs,
        CronTrigger(hour=3, minute=20),
        id="event_assignment_log_retention",
        name="Event assignment diagnostic retention",
    )

    logger.info(f"Scheduler configured with {len(scheduler.get_jobs())} jobs")


def trigger_startup_jobs() -> None:
    """Best-effort startup catch-up for time-sensitive jobs."""
    from app.domains.enrich.hourly.tasks import generate_previous_hour_digest

    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(_run_durable("generate_hourly_digest", generate_previous_hour_digest))
        _startup_tasks.add(task)
        task.add_done_callback(_startup_tasks.discard)
    except RuntimeError:
        logger.warning("Skip startup digest catch-up: no running event loop")
