"""Durable scheduler run ledger with idempotent business run keys."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import inspect
from typing import Callable

from sqlalchemy.exc import IntegrityError

from app.models.reliable_execution import SchedulerRun
from app.platform.observability.metrics import reliability_metrics
from app.platform.persistence.database import SessionLocal
from app.utils.datetime import utcnow_naive


def scheduler_business_key(schedule_id: str, scheduled_for: datetime, *, bucket_seconds: int = 60) -> str:
    seconds = max(1, int(bucket_seconds))
    epoch = int(scheduled_for.timestamp())
    bucket = datetime.utcfromtimestamp(epoch - (epoch % seconds))
    return f"{schedule_id}:{bucket.isoformat()}"


def create_scheduler_run(
    schedule_id: str,
    *,
    scheduled_for: datetime | None = None,
    business_run_key: str | None = None,
    policy_version: str = "v1",
    misfire_reason: str | None = None,
) -> tuple[str, bool]:
    scheduled = scheduled_for or utcnow_naive()
    key = business_run_key or scheduler_business_key(schedule_id, scheduled)
    db = SessionLocal()
    try:
        existing = db.query(SchedulerRun).filter(
            SchedulerRun.schedule_id == schedule_id,
            SchedulerRun.business_run_key == key,
        ).first()
        if existing is not None:
            return str(existing.id), False
        run = SchedulerRun(
            schedule_id=schedule_id,
            business_run_key=key,
            scheduled_for=scheduled,
            policy_version=policy_version,
            state="pending",
            misfire_reason=misfire_reason,
        )
        db.add(run)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = db.query(SchedulerRun).filter(
                SchedulerRun.schedule_id == schedule_id,
                SchedulerRun.business_run_key == key,
            ).one()
            return str(existing.id), False
        return str(run.id), True
    finally:
        db.close()


async def execute_scheduled(
    schedule_id: str,
    callback: Callable,
    *,
    scheduled_for: datetime | None = None,
    business_run_key: str | None = None,
    misfire_reason: str | None = None,
) -> dict[str, object]:
    run_id, created = await asyncio.to_thread(
        create_scheduler_run,
        schedule_id,
        scheduled_for=scheduled_for,
        business_run_key=business_run_key,
        misfire_reason=misfire_reason,
    )
    if not created:
        reliability_metrics.record("scheduler_deduplicated")
        return {"run_id": run_id, "duplicate": True, "state": "deduplicated"}
    now = utcnow_naive()
    db = SessionLocal()
    try:
        changed = db.query(SchedulerRun).filter(
            SchedulerRun.id == run_id,
            SchedulerRun.state == "pending",
        ).update(
            {"state": "running", "started_at": now, "updated_at": now},
            synchronize_session=False,
        )
        db.commit()
        if changed != 1:
            return {"run_id": run_id, "duplicate": True, "state": "deduplicated"}
    finally:
        db.close()

    try:
        result = await callback() if inspect.iscoroutinefunction(callback) else await asyncio.to_thread(callback)
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        db = SessionLocal()
        try:
            run = db.query(SchedulerRun).filter(SchedulerRun.id == run_id).one()
            run.state = "failed"
            run.error = str(exc)[:4000]
            run.completed_at = utcnow_naive()
            run.updated_at = utcnow_naive()
            db.commit()
        finally:
            db.close()
        reliability_metrics.record("scheduler_failed")
        raise

    created_job_ids = []
    if isinstance(result, dict):
        ids = result.get("job_ids") or result.get("created_job_ids") or []
        if isinstance(ids, list):
            created_job_ids = [str(item) for item in ids]
    db = SessionLocal()
    try:
        run = db.query(SchedulerRun).filter(SchedulerRun.id == run_id).one()
        run.state = "succeeded"
        run.created_job_ids = created_job_ids
        run.completed_at = utcnow_naive()
        run.updated_at = utcnow_naive()
        db.commit()
    finally:
        db.close()
    reliability_metrics.record("scheduler_succeeded")
    return {"run_id": run_id, "duplicate": False, "state": "succeeded", "result": result}


def record_misfires(
    schedule_id: str,
    scheduled_times: list[datetime],
    *,
    catch_up_window: timedelta,
    max_compensation: int,
) -> dict[str, list[str]]:
    """Persist bounded catch-up candidates and explicit skips."""
    now = utcnow_naive()
    eligible = [value for value in sorted(set(scheduled_times)) if value <= now]
    catch_up = [value for value in eligible if value >= now - catch_up_window]
    catch_up = catch_up[-max(0, int(max_compensation)):]
    catch_up_set = set(catch_up)
    result = {"caught_up": [], "skipped": []}
    for scheduled_for in eligible:
        run_id, created = create_scheduler_run(
            schedule_id,
            scheduled_for=scheduled_for,
            misfire_reason="service_downtime",
        )
        if not created:
            continue
        db = SessionLocal()
        try:
            run = db.query(SchedulerRun).filter(SchedulerRun.id == run_id).one()
            if scheduled_for in catch_up_set:
                result["caught_up"].append(run_id)
            else:
                run.state = "skipped"
                run.completed_at = now
                result["skipped"].append(run_id)
            run.updated_at = now
            db.commit()
        finally:
            db.close()
    return result


__all__ = ["create_scheduler_run", "execute_scheduled", "record_misfires", "scheduler_business_key"]
