"""APScheduler-based task scheduling replacing Celery Beat."""

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Cron/interval jobs: avoid APScheduler defaults (misfire_grace_time=1s, coalesce=False)
# which silently skip runs after a >1s stall; keep overlapping runs from piling up.
_JOB_DEFAULTS = {
    "misfire_grace_time": 300,
    "coalesce": True,
    "max_instances": 1,
}

scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")


def setup_scheduler():
    """Register all scheduled jobs."""
    from app.tasks.fetch_tasks import check_and_fetch_due_sources
    from app.domains.enrich.hourly.tasks import generate_previous_hour_digest
    from app.tasks.maintenance_tasks import (
        cleanup_old_content,
        cleanup_error_logs,
        purge_expired_runtime_locks,
        run_markdown_export,
    )
    from app.tasks.email_tasks import send_daily_digest_emails, send_doctor_digest_email

    # Core: check sources every 5 minutes (fetch priority)
    scheduler.add_job(
        check_and_fetch_due_sources,
        IntervalTrigger(minutes=5),
        id="check_and_fetch_due_sources",
        name="Check and fetch due sources",
        replace_existing=True,
        **_JOB_DEFAULTS,
    )

    # Digest should always be registered when the feature is visible in the UI.
    # It now runs on completed 3-hour boundaries; runtime availability is
    # checked inside the task itself.
    scheduler.add_job(
        generate_previous_hour_digest,
        CronTrigger(hour="*/3", minute=0),
        id="generate_hourly_digest",
        name="Generate 3-hour digest",
        replace_existing=True,
        **_JOB_DEFAULTS,
    )

    scheduler.add_job(
        send_daily_digest_emails,
        CronTrigger(hour=8, minute=0),
        id="send_daily_digest_emails",
        name="Send daily digest emails",
        replace_existing=True,
        **_JOB_DEFAULTS,
    )

    # Daily DoctorService digest — silent on green, alert on degraded/error.
    # Runs a few minutes after the digest email so operators get one
    # combined morning triage.
    scheduler.add_job(
        send_doctor_digest_email,
        CronTrigger(hour=8, minute=5),
        id="send_doctor_digest_email",
        name="Daily PIM doctor digest (alerts only)",
        replace_existing=True,
        **_JOB_DEFAULTS,
    )

    # Maintenance: weekly cleanup (Sunday 3am)
    scheduler.add_job(
        cleanup_old_content,
        CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="cleanup_old_content",
        name="Weekly content cleanup",
        replace_existing=True,
        **_JOB_DEFAULTS,
    )

    # Maintenance: reset error counts for recovered sources
    scheduler.add_job(
        cleanup_error_logs,
        CronTrigger(hour="*/6", minute=30),
        id="cleanup_error_logs",
        name="Reset recovered source error counts",
        replace_existing=True,
        **_JOB_DEFAULTS,
    )

    scheduler.add_job(
        purge_expired_runtime_locks,
        CronTrigger(minute=15),
        id="purge_expired_runtime_locks",
        name="Purge expired runtime fetch locks",
        replace_existing=True,
        **_JOB_DEFAULTS,
    )

    scheduler.add_job(
        run_markdown_export,
        CronTrigger(minute=30),  # 每小时 30 分执行
        id="markdown_export",
        name="Incremental markdown export",
        replace_existing=True,
        **_JOB_DEFAULTS,
    )

    logger.info(f"Scheduler configured with {len(scheduler.get_jobs())} jobs")


def trigger_startup_jobs() -> None:
    """Best-effort startup catch-up for time-sensitive jobs."""
    from app.domains.enrich.hourly.tasks import generate_previous_hour_digest

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(generate_previous_hour_digest())
    except RuntimeError:
        logger.warning("Skip startup digest catch-up: no running event loop")
