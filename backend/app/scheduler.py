"""APScheduler-based task scheduling replacing Celery Beat."""

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.utils.logger import get_logger

logger = get_logger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")


def setup_scheduler():
    """Register all scheduled jobs."""
    from app.tasks.fetch_tasks import check_and_fetch_due_sources
    from app.tasks.hourly_digest_tasks import generate_previous_hour_digest
    from app.tasks.maintenance_tasks import cleanup_old_content, cleanup_error_logs
    from app.tasks.email_tasks import send_daily_digest_emails

    # Core: check sources every 5 minutes (fetch priority)
    scheduler.add_job(
        check_and_fetch_due_sources,
        IntervalTrigger(minutes=5),
        id="check_and_fetch_due_sources",
        name="Check and fetch due sources",
        replace_existing=True,
    )

    # Hourly digest should always be registered when the feature is visible in the UI.
    # Runtime availability is checked inside the task itself.
    scheduler.add_job(
        generate_previous_hour_digest,
        CronTrigger(minute=0),
        id="generate_hourly_digest",
        name="Generate hourly digest",
        replace_existing=True,
    )

    scheduler.add_job(
        send_daily_digest_emails,
        CronTrigger(hour=8, minute=0),
        id="send_daily_digest_emails",
        name="Send daily digest emails",
        replace_existing=True,
    )

    # Maintenance: weekly cleanup (Sunday 3am)
    scheduler.add_job(
        cleanup_old_content,
        CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="cleanup_old_content",
        name="Weekly content cleanup",
        replace_existing=True,
    )

    # Maintenance: reset error counts for recovered sources
    scheduler.add_job(
        cleanup_error_logs,
        CronTrigger(hour="*/6", minute=30),
        id="cleanup_error_logs",
        name="Reset recovered source error counts",
        replace_existing=True,
    )

    logger.info(f"Scheduler configured with {len(scheduler.get_jobs())} jobs")


def trigger_startup_jobs() -> None:
    """Best-effort startup catch-up for time-sensitive jobs."""
    from app.tasks.hourly_digest_tasks import generate_previous_hour_digest

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(generate_previous_hour_digest())
    except RuntimeError:
        logger.warning("Skip startup digest catch-up: no running event loop")
