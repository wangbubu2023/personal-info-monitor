"""Budgeted Event rebalance that only emits merge/split suggestions."""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from datetime import timedelta
from itertools import combinations
from typing import Any

from sqlalchemy.orm import Session

from app.domains.events.config import assignment_log_retention_days, event_config, event_rebalance_enabled
from app.domains.score.ranking import _jaccard
from app.models import ContentEvent, EventAssignmentLog, EventRebalanceRun, EventRebalanceSuggestion, ScoreFeedback
from app.platform.observability.metrics import event_metrics, reliability_metrics
from app.utils.datetime import utcnow_naive


def _signature(event: ContentEvent) -> dict[str, Any]:
    centroid = event.centroid if isinstance(event.centroid, dict) else {}
    value = centroid.get("signature")
    return value if isinstance(value, dict) else {}


def _block_keys(event: ContentEvent) -> set[str]:
    signature = _signature(event)
    keys: set[str] = set()
    for row in signature.get("identifiers") or []:
        if row.get("value"):
            keys.add(f"id:{row.get('type')}:{str(row.get('value')).lower()}")
    for row in (signature.get("normalized_entities") or [])[:4]:
        if row.get("canonical_id"):
            keys.add(f"entity:{row.get('canonical_id')}")
    action = (signature.get("trigger_action") or {}).get("lemma")
    if action:
        keys.add(f"action:{action}")
    return keys


def _pair_score(left: ContentEvent, right: ContentEvent) -> dict[str, Any]:
    left_tokens = set((left.centroid or {}).get("tokens") or [])
    right_tokens = set((right.centroid or {}).get("tokens") or [])
    lexical = _jaccard(left_tokens, right_tokens)
    common_blocks = _block_keys(left) & _block_keys(right)
    identifier = any(key.startswith("id:") for key in common_blocks)
    score = 0.55 * lexical + 0.3 * min(1.0, len(common_blocks) / 2) + 0.15 * float(identifier)
    return {"score": round(score, 4), "lexical": round(lexical, 4), "common_blocks": sorted(common_blocks)}


def run_rebalance(
    db: Session,
    *,
    run_kind: str,
    max_events: int = 1000,
    max_pairs: int = 5000,
    max_runtime_seconds: float = 30.0,
    checkpoint_size: int = 100,
    resume_cursor: str | None = None,
) -> dict[str, Any]:
    if not event_rebalance_enabled():
        return {"status": "skipped", "reason": "feature_disabled"}
    if run_kind not in {"light", "deep"}:
        raise ValueError("run_kind must be light or deep")
    config = event_config()
    now = utcnow_naive()
    started = time.perf_counter()
    budgets = {
        "max_events": max_events,
        "max_pairs": max_pairs,
        "max_runtime_seconds": max_runtime_seconds,
        "checkpoint_size": checkpoint_size,
    }
    run = EventRebalanceRun(
        run_kind=run_kind,
        status="running",
        config_version=config.cluster_version,
        cursor=resume_cursor,
        budgets=budgets,
        started_at=now,
        created_at=now,
    )
    db.add(run)
    db.flush()
    activity_cutoff = now - timedelta(days=2 if run_kind == "light" else 14)
    base = (
        db.query(ContentEvent)
        .filter(ContentEvent.cluster_version == config.cluster_version)
        .filter(ContentEvent.status.in_(["active", "cooling", "reopened"]))
        .filter(ContentEvent.last_material_update_at >= activity_cutoff)
        .order_by(ContentEvent.event_id)
    )
    if resume_cursor:
        base = base.filter(ContentEvent.event_id > resume_cursor)
    events = base.limit(max(1, max_events)).all()
    filtered_closed = (
        db.query(ContentEvent)
        .filter(ContentEvent.cluster_version == config.cluster_version)
        .filter(ContentEvent.status.in_(["closed", "archived"]))
        .count()
    )
    feedback_event_ids = {
        str((row.snapshot or {}).get("event_id") or "")
        for row in (
            db.query(ScoreFeedback)
            .filter(ScoreFeedback.event_type.in_(["event_wrong_merge", "event_missing_merge"]))
            .all()
        )
        if (row.snapshot or {}).get("event_id")
    }
    wake_reasons = {"activity_window": len(events), "explicit_feedback": len(feedback_event_ids)}
    blocks: dict[str, list[ContentEvent]] = defaultdict(list)
    for event in events:
        keys = _block_keys(event)
        if event.event_id in feedback_event_ids:
            keys.add(f"feedback:{event.event_id}")
        for key in keys:
            # Bound pathological entity/action blocks before pair generation.
            if len(blocks[key]) < 50:
                blocks[key].append(event)
    seen_pairs: set[tuple[str, str]] = set()
    candidate_pairs = 0
    suggestion_count = 0
    checkpoint_count = 0
    cursor = resume_cursor
    budget_exhausted = False
    for block_key in sorted(blocks):
        for left, right in combinations(sorted(blocks[block_key], key=lambda row: row.event_id), 2):
            pair = tuple(sorted((left.event_id, right.event_id)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            candidate_pairs += 1
            cursor = max(pair)
            if candidate_pairs % max(1, checkpoint_size) == 0:
                checkpoint_count += 1
                run.cursor = cursor
                db.flush()
            if candidate_pairs > max_pairs or time.perf_counter() - started >= max_runtime_seconds:
                budget_exhausted = True
                break
            scores = _pair_score(left, right)
            if scores["score"] < 0.78:
                continue
            fingerprint = hashlib.sha256(
                json.dumps({"type": "merge", "events": list(pair), "version": config.cluster_version}, sort_keys=True).encode()
            ).hexdigest()
            existing = (
                db.query(EventRebalanceSuggestion)
                .filter(
                    EventRebalanceSuggestion.suggestion_type == "merge",
                    EventRebalanceSuggestion.fingerprint == fingerprint,
                )
                .first()
            )
            if existing is None:
                db.add(
                    EventRebalanceSuggestion(
                        run_id=run.id,
                        suggestion_type="merge",
                        event_ids=list(pair),
                        reason=f"blocked by {block_key}; high structural/lexical compatibility",
                        scores=scores,
                        evidence={"block_key": block_key},
                        fingerprint=fingerprint,
                        status="pending",
                        created_at=utcnow_naive(),
                    )
                )
                suggestion_count += 1
                reliability_metrics.record("event_merge_suggestion")
                event_metrics.increment("pim_event_merge_suggestion_total")
        if budget_exhausted:
            break
    for event in events:
        if float(event.dispersion or 0.0) < 0.65 and event.event_id not in feedback_event_ids:
            continue
        fingerprint = hashlib.sha256(
            json.dumps({"type": "split", "event": event.event_id, "version": config.cluster_version}, sort_keys=True).encode()
        ).hexdigest()
        exists = (
            db.query(EventRebalanceSuggestion)
            .filter(
                EventRebalanceSuggestion.suggestion_type == "split",
                EventRebalanceSuggestion.fingerprint == fingerprint,
            )
            .first()
        )
        if exists is None:
            db.add(
                EventRebalanceSuggestion(
                    run_id=run.id,
                    suggestion_type="split",
                    event_ids=[event.event_id],
                    reason="high dispersion or explicit wrong-merge feedback",
                    scores={"dispersion": float(event.dispersion or 0.0)},
                    evidence={"feedback_wake": event.event_id in feedback_event_ids},
                    fingerprint=fingerprint,
                    status="pending",
                    created_at=utcnow_naive(),
                )
            )
            suggestion_count += 1
            reliability_metrics.record("event_split_suggestion")
            event_metrics.increment("pim_event_split_suggestion_total")
        event.last_rebalanced_at = utcnow_naive()
    run.status = "checkpointed" if budget_exhausted else "completed"
    run.cursor = cursor
    run.scanned_event_count = len(events)
    run.candidate_pair_count = min(candidate_pairs, max_pairs)
    run.filtered_closed_count = filtered_closed
    run.checkpoint_count = checkpoint_count
    run.wake_reasons = wake_reasons
    run.summary = {
        "suggestion_count": suggestion_count,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "budget_exhausted": budget_exhausted,
        "closed_pair_comparisons": 0,
    }
    run.completed_at = utcnow_naive()
    reliability_metrics.record(f"event_rebalance:{run_kind}:{run.status}")
    return {
        "run_id": str(run.id),
        "status": run.status,
        "cursor": run.cursor,
        "scanned_event_count": run.scanned_event_count,
        "candidate_pair_count": run.candidate_pair_count,
        "filtered_closed_count": run.filtered_closed_count,
        "checkpoint_count": run.checkpoint_count,
        "wake_reasons": run.wake_reasons,
        **run.summary,
    }


def run_event_rebalance_light() -> dict[str, Any]:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        result = run_rebalance(db, run_kind="light", max_events=500, max_pairs=1500, max_runtime_seconds=15)
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def run_event_rebalance_deep() -> dict[str, Any]:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        previous = (
            db.query(EventRebalanceRun)
            .filter(EventRebalanceRun.run_kind == "deep", EventRebalanceRun.status == "checkpointed")
            .order_by(EventRebalanceRun.created_at.desc())
            .first()
        )
        result = run_rebalance(
            db,
            run_kind="deep",
            max_events=1000,
            max_pairs=5000,
            max_runtime_seconds=30,
            checkpoint_size=100,
            resume_cursor=previous.cursor if previous else None,
        )
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def cleanup_event_assignment_logs() -> dict[str, int]:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        cutoff = utcnow_naive() - timedelta(days=assignment_log_retention_days())
        deleted = (
            db.query(EventAssignmentLog)
            .filter(EventAssignmentLog.created_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
        return {"deleted": int(deleted), "retention_days": assignment_log_retention_days()}
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


__all__ = [
    "cleanup_event_assignment_logs",
    "run_event_rebalance_deep",
    "run_event_rebalance_light",
    "run_rebalance",
]
