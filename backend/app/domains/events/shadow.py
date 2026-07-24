"""Canonical v1 Today reads and immutable v0/v1 diff audits."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.domains.events.config import event_config
from app.models import ContentEvent, ContentEventSnapshot, EventTodayDiffAudit
from app.utils.datetime import to_iso_z, utcnow_naive


def _fingerprint(items: list[dict[str, Any]]) -> str:
    stable = [
        {
            "event_id": row.get("event_id"),
            "snapshot_version": row.get("snapshot_version") or row.get("latest_version"),
            "rank": index,
        }
        for index, row in enumerate(items, start=1)
    ]
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode("utf-8")).hexdigest()


def _card(event: ContentEvent, snapshot: ContentEventSnapshot) -> dict[str, Any]:
    explanation = snapshot.explanation if isinstance(snapshot.explanation, dict) else {}
    return {
        "event_id": event.event_id,
        "event_key": event.event_key,
        "section": event.event_state,
        "title": snapshot.title,
        "summary": snapshot.summary,
        "why_matters": explanation.get("selection_reason") or snapshot.why_matters,
        "what_changed": explanation.get("what_changed_since_last_read") or snapshot.what_changed,
        "independent_source_count": int(event.independent_source_count or 0),
        "source_names": event.source_names or [],
        "updated_at": to_iso_z(event.last_material_update_at or snapshot.created_at),
        "importance_score": event.importance_score,
        "confidence_score": event.confidence_score,
        "primary_content_id": str(snapshot.canonical_content_id or event.canonical_content_id or "") or None,
        "snapshot_version": int(snapshot.version),
        "latest_version": int(snapshot.version),
        "user_seen_version": 0,
        "has_updates": False,
        "event_state": event.event_state,
        "change_type": snapshot.change_type,
    }


def build_v1_today_cards(db: Session, target_date: date, *, limit: int = 8) -> list[dict[str, Any]]:
    start = datetime.combine(target_date, time.min)
    end = start + timedelta(days=1)
    events = (
        db.query(ContentEvent)
        .filter(ContentEvent.cluster_version == event_config().cluster_version)
        .filter(ContentEvent.status.in_(["active", "cooling", "reopened"]))
        .filter(ContentEvent.event_state.in_(["need_to_know", "developing"]))
        .filter(ContentEvent.last_material_update_at >= start, ContentEvent.last_material_update_at < end)
        .order_by(
            ContentEvent.importance_score.desc().nulls_last(),
            ContentEvent.last_material_update_at.desc(),
            ContentEvent.event_id,
        )
        .limit(max(1, min(8, int(limit))))
        .all()
    )
    cards = []
    for event in events:
        snapshot = (
            db.query(ContentEventSnapshot)
            .filter(
                ContentEventSnapshot.event_id == event.event_id,
                ContentEventSnapshot.version == event.latest_snapshot_version,
            )
            .first()
        )
        if snapshot is not None:
            cards.append(_card(event, snapshot))
    return cards


async def list_v1_today_cards(db: AsyncSession, target_date: date, *, limit: int = 8) -> list[dict[str, Any]]:
    start = datetime.combine(target_date, time.min)
    end = start + timedelta(days=1)
    rows = (
        await db.execute(
            select(ContentEvent, ContentEventSnapshot)
            .join(
                ContentEventSnapshot,
                (ContentEventSnapshot.event_id == ContentEvent.event_id)
                & (ContentEventSnapshot.version == ContentEvent.latest_snapshot_version),
            )
            .where(
                ContentEvent.cluster_version == event_config().cluster_version,
                ContentEvent.status.in_(["active", "cooling", "reopened"]),
                ContentEvent.event_state.in_(["need_to_know", "developing"]),
                ContentEvent.last_material_update_at >= start,
                ContentEvent.last_material_update_at < end,
            )
            .order_by(
                ContentEvent.importance_score.desc().nulls_last(),
                ContentEvent.last_material_update_at.desc(),
                ContentEvent.event_id,
            )
            .limit(max(1, min(8, int(limit))))
        )
    ).all()
    return [_card(event, snapshot) for event, snapshot in rows]


def record_today_diff_audit(
    db: Session,
    *,
    target_date: date,
    v0_items: list[dict[str, Any]],
    v1_items: list[dict[str, Any]] | None = None,
) -> EventTodayDiffAudit:
    v1 = v1_items if v1_items is not None else build_v1_today_cards(db, target_date, limit=8)
    safe_v0 = [
        {
            "event_id": row.get("event_id"),
            "snapshot_version": row.get("snapshot_version"),
            "rank": index,
        }
        for index, row in enumerate(v0_items, start=1)
    ]
    safe_v1 = [
        {
            "event_id": row.get("event_id"),
            "snapshot_version": row.get("snapshot_version"),
            "rank": index,
        }
        for index, row in enumerate(v1, start=1)
    ]
    v0_fp = _fingerprint(safe_v0)
    v1_fp = _fingerprint(safe_v1)
    existing = (
        db.query(EventTodayDiffAudit)
        .filter(
            EventTodayDiffAudit.audit_date == target_date.isoformat(),
            EventTodayDiffAudit.v0_digest_fingerprint == v0_fp,
            EventTodayDiffAudit.v1_fingerprint == v1_fp,
        )
        .first()
    )
    if existing is not None:
        return existing
    v0_ids = [str(row.get("event_id")) for row in safe_v0 if row.get("event_id")]
    v1_ids = [str(row.get("event_id")) for row in safe_v1 if row.get("event_id")]
    rank_delta = {
        event_id: {"v0": v0_ids.index(event_id) + 1, "v1": v1_ids.index(event_id) + 1}
        for event_id in sorted(set(v0_ids) & set(v1_ids))
        if v0_ids.index(event_id) != v1_ids.index(event_id)
    }
    audit = EventTodayDiffAudit(
        audit_date=target_date.isoformat(),
        v0_digest_fingerprint=v0_fp,
        v1_fingerprint=v1_fp,
        v0_items=safe_v0,
        v1_items=safe_v1,
        diff={
            "only_v0": sorted(set(v0_ids) - set(v1_ids)),
            "only_v1": sorted(set(v1_ids) - set(v0_ids)),
            "rank_delta": rank_delta,
            "redirects": [],
            "wrong_merge_samples": [],
            "missing_merge_samples": [],
        },
        assignment_version=event_config().cluster_version,
        shadow_only=True,
        production_affected=False,
        created_at=utcnow_naive(),
    )
    db.add(audit)
    return audit


def freeze_digest_snapshot_refs(db: Session, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach an immutable display snapshot to each legacy digest reference."""

    frozen: list[dict[str, Any]] = []
    for rank, item in enumerate(items, start=1):
        row = dict(item)
        event_id = str(row.get("event_id") or "")
        snapshot = (
            db.query(ContentEventSnapshot)
            .filter(ContentEventSnapshot.event_id == event_id)
            .order_by(ContentEventSnapshot.version.desc())
            .first()
        )
        if snapshot is not None:
            row["snapshot_version"] = int(snapshot.version)
            row["rank_context"] = {
                "rank": rank,
                "importance_score": row.get("importance_score"),
                "section": row.get("section"),
                "ranking_version": "pim-score-v2",
            }
            row["display_snapshot"] = {
                "title": snapshot.title,
                "summary": snapshot.summary,
                "what_changed": snapshot.what_changed,
                "why_matters": snapshot.why_matters,
                "source_names": row.get("source_names") or [],
                "captured_at": to_iso_z(utcnow_naive()),
            }
        frozen.append(row)
    return frozen


__all__ = [
    "build_v1_today_cards",
    "freeze_digest_snapshot_refs",
    "list_v1_today_cards",
    "record_today_diff_audit",
]
