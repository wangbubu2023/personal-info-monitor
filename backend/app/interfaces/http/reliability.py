"""Operator API for durable jobs, scheduler runs, outbox, and lineage."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.models import FetchJob, PostprocessJob
from app.models.reliable_execution import NotificationDelivery, OutboxEvent, SchedulerRun
from app.platform.persistence.database import SessionLocal
from app.platform.persistence.lineage import trace_lineage
from app.utils.datetime import to_iso_z, utcnow_naive

router = APIRouter()


def _job_dict(job, job_type: str) -> dict[str, Any]:
    state = job.state if job_type == "fetch" else job.status
    return {
        "id": str(job.id),
        "job_type": job_type,
        "business_key": job.business_key if job_type == "fetch" else job.idempotency_key,
        "state": state,
        "priority": int(job.priority or 0),
        "attempt": int(job.attempts or 0),
        "max_attempts": int(job.max_attempts or 0),
        "locked_by": job.locked_by,
        "lease_expires_at": to_iso_z(job.lease_expires_at),
        "heartbeat_at": to_iso_z(job.heartbeat_at),
        "failure_code": job.failure_code,
        "created_at": to_iso_z(job.created_at),
        "completed_at": to_iso_z(job.completed_at if job_type == "fetch" else job.finished_at),
    }


@router.get("/jobs")
def list_jobs(state: str | None = None, limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    db = SessionLocal()
    try:
        fetch = db.query(FetchJob)
        postprocess = db.query(PostprocessJob)
        if state:
            fetch = fetch.filter(FetchJob.state == state)
            postprocess = postprocess.filter(PostprocessJob.status == state)
        rows = [
            *[_job_dict(row, "fetch") for row in fetch.order_by(FetchJob.created_at.desc()).limit(limit).all()],
            *[
                _job_dict(row, "postprocess")
                for row in postprocess.order_by(PostprocessJob.created_at.desc()).limit(limit).all()
            ],
        ]
        rows.sort(key=lambda item: item["created_at"] or "", reverse=True)
        return {"items": rows[:limit]}
    finally:
        db.close()


@router.get("/scheduler-runs")
def list_scheduler_runs(state: str | None = None, limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    db = SessionLocal()
    try:
        query = db.query(SchedulerRun)
        if state:
            query = query.filter(SchedulerRun.state == state)
        rows = query.order_by(SchedulerRun.scheduled_for.desc(), SchedulerRun.id.desc()).limit(limit).all()
        return {
            "items": [
                {
                    "id": str(row.id),
                    "schedule_id": row.schedule_id,
                    "business_run_key": row.business_run_key,
                    "scheduled_for": to_iso_z(row.scheduled_for),
                    "state": row.state,
                    "created_job_ids": row.created_job_ids,
                    "misfire_reason": row.misfire_reason,
                    "error": row.error,
                }
                for row in rows
            ]
        }
    finally:
        db.close()


@router.get("/outbox")
def list_outbox(state: str | None = None, limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    db = SessionLocal()
    try:
        query = db.query(OutboxEvent)
        if state:
            query = query.filter(OutboxEvent.state == state)
        rows = query.order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc()).limit(limit).all()
        items = []
        for row in rows:
            deliveries = db.query(NotificationDelivery).filter(NotificationDelivery.outbox_id == row.id).all()
            items.append(
                {
                    "id": str(row.id),
                    "event_type": row.event_type,
                    "aggregate_type": row.aggregate_type,
                    "aggregate_id": row.aggregate_id,
                    "state": row.state,
                    "attempt": row.attempt,
                    "available_at": to_iso_z(row.available_at),
                    "last_error": row.last_error,
                    "deliveries": [
                        {
                            "id": str(delivery.id),
                            "channel": delivery.channel,
                            "recipient": delivery.recipient_ref,
                            "provider": delivery.provider,
                            "state": delivery.state,
                            "response_code": delivery.response_code,
                            "response_excerpt": delivery.response_excerpt,
                            "latency_ms": delivery.latency_ms,
                            "attempt": delivery.attempt,
                        }
                        for delivery in deliveries
                    ],
                }
            )
        return {"items": items}
    finally:
        db.close()


@router.post("/outbox/{event_id}/retry")
def retry_outbox(event_id: str) -> dict[str, str]:
    db = SessionLocal()
    try:
        event = db.query(OutboxEvent).filter(OutboxEvent.id == event_id).first()
        if event is None:
            raise HTTPException(status_code=404, detail="Outbox event not found")
        if event.state == "delivered":
            raise HTTPException(status_code=409, detail="Delivered event cannot be retried")
        event.state = "pending"
        event.available_at = utcnow_naive()
        event.locked_by = None
        event.lease_token = None
        event.lease_expires_at = None
        event.updated_at = utcnow_naive()
        db.commit()
        return {"id": event_id, "state": "pending"}
    finally:
        db.close()


@router.post("/outbox/{event_id}/cancel")
def cancel_outbox(event_id: str) -> dict[str, str]:
    db = SessionLocal()
    try:
        event = db.query(OutboxEvent).filter(OutboxEvent.id == event_id).first()
        if event is None:
            raise HTTPException(status_code=404, detail="Outbox event not found")
        if event.state == "delivered":
            raise HTTPException(status_code=409, detail="Delivered event cannot be cancelled")
        event.state = "cancelled"
        event.locked_by = None
        event.lease_token = None
        event.lease_expires_at = None
        event.updated_at = utcnow_naive()
        db.commit()
        return {"id": event_id, "state": "cancelled"}
    finally:
        db.close()


@router.get("/lineage/{object_type}/{object_id}")
def get_lineage(
    object_type: str,
    object_id: str,
    direction: str = Query("upstream", pattern="^(upstream|downstream)$"),
    max_hops: int = Query(3, ge=1, le=10),
) -> dict[str, Any]:
    return {
        "object_type": object_type,
        "object_id": object_id,
        "direction": direction,
        "edges": trace_lineage(object_type, object_id, direction=direction, max_hops=max_hops),
    }


__all__ = ["router"]
