from __future__ import annotations

from app.scheduler import scheduler, setup_scheduler


def test_hourly_digest_job_is_always_registered():
    scheduler.remove_all_jobs()
    setup_scheduler()

    job_ids = {job.id for job in scheduler.get_jobs()}

    assert "check_and_fetch_due_sources" in job_ids
    assert "generate_hourly_digest" in job_ids
    assert "send_daily_digest_emails" in job_ids
    assert "purge_expired_runtime_locks" in job_ids
    assert "requeue_unfinished_content" in job_ids

    scheduler.remove_all_jobs()


def test_scheduler_timezone_comes_from_settings_default():
    assert str(scheduler.timezone) == "Asia/Shanghai"
