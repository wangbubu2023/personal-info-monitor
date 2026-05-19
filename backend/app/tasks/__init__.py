"""Background tasks package (APScheduler + asyncio)."""

from app.domains.ingest.finish import finish_content
from app.tasks.fetch_tasks import fetch_source, fetch_all_sources, check_and_fetch_due_sources
from app.tasks.process_tasks import process_new_content, process_content, update_keyword_matches
from app.tasks.email_tasks import send_daily_digest_emails, send_keyword_alert
from app.tasks.maintenance_tasks import cleanup_old_content, cleanup_error_logs
from app.domains.enrich.hourly.tasks import (
    clear_hourly_digests,
    generate_previous_hour_digest,
)

__all__ = [
    "fetch_source",
    "fetch_all_sources",
    "check_and_fetch_due_sources",
    "finish_content",
    "process_new_content",
    "process_content",
    "update_keyword_matches",
    "send_daily_digest_emails",
    "send_keyword_alert",
    "cleanup_old_content",
    "cleanup_error_logs",
    "clear_hourly_digests",
    "generate_previous_hour_digest",
]
