"""Idempotent Event lifecycle transitions."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.domains.events.config import event_config
from app.models import ContentEvent, EventOperation
from app.platform.observability.metrics import event_metrics, reliability_metrics
from app.utils.datetime import utcnow_naive


def _event_type(event: ContentEvent) -> str:
    metadata = event.metadata_ if isinstance(event.metadata_, dict) else {}
    explicit = str(metadata.get("event_type") or metadata.get("lane") or "").lower()
    if explicit in {"policy", "legal", "product", "breaking"}:
        return explicit
    action = str(((event.centroid or {}).get("signature") or {}).get("trigger_action", {}).get("lemma") or "")
    if action == "launch":
        return "product"
    if action in {"sue", "investigate"}:
        return "legal"
    return "default"


def lifecycle_tick(db: Session) -> dict[str, int]:
    now = utcnow_naive()
    config = event_config()
    changed = {"active_to_cooling": 0, "cooling_to_closed": 0, "reopened_to_active": 0}
    events = (
        db.query(ContentEvent)
        .filter(ContentEvent.cluster_version == config.cluster_version)
        .filter(ContentEvent.status.in_(["active", "cooling", "reopened"]))
        .all()
    )
    for event in events:
        event_type = _event_type(event)
        ttl = timedelta(hours=config.active_ttl_hours.get(event_type, config.active_ttl_hours["default"]))
        anchor = event.last_material_update_at or event.last_seen_at or event.updated_at or event.created_at
        previous = event.status
        previous_reason = event.lifecycle_reason
        next_status = previous
        reason = None
        if previous == "reopened":
            next_status = "active"
            reason = "reopen acknowledged by lifecycle tick"
            changed["reopened_to_active"] += 1
        elif previous == "active" and anchor and now - anchor >= ttl:
            next_status = "cooling"
            reason = f"no material update for {int(ttl.total_seconds() / 3600)}h"
            changed["active_to_cooling"] += 1
        elif previous == "cooling" and anchor and now - anchor >= ttl * 2:
            next_status = "closed"
            reason = f"no material update for {int(ttl.total_seconds() / 1800)}h"
            changed["cooling_to_closed"] += 1
        if next_status == previous:
            continue
        event.status = next_status
        event.lifecycle_reason = reason
        event.updated_at = now
        db.add(
            EventOperation(
                event_id=event.event_id,
                operation_type="lifecycle",
                input_event_ids=[event.event_id],
                output_event_ids=[event.event_id],
                reason=reason,
                actor="system:event_lifecycle_tick",
                checkpoint=f"{previous}->{next_status}",
                rollback_payload={"status": previous, "lifecycle_reason": previous_reason},
                created_at=now,
            )
        )
        reliability_metrics.record(f"event_lifecycle:{previous}_to_{next_status}")
        if next_status == "reopened":
            event_metrics.increment("pim_event_reopened_total")
    event_metrics.gauge("pim_event_active_count", sum(event.status in {"active", "reopened"} for event in events))
    return changed


def run_lifecycle_tick() -> dict[str, int]:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        result = lifecycle_tick(db)
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


__all__ = ["lifecycle_tick", "run_lifecycle_tick"]
