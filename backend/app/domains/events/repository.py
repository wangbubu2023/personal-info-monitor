"""Repository helpers for stable Event v0.

The first production slice is deliberately deterministic and DB-light:
``RankingService`` still performs the hybrid clustering inside the hourly
pipeline, then this repository persists stable event identities and membership
snapshots. Duplicate groups remain article-level facts and are only used as one
possible clustering signal.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.session import Session

from app.domains.events.personal_state import get_event_read_state, get_or_create_item_state
from app.models import Content, ContentEvent, ContentEventMembership, ContentEventSnapshot, HourlyDigest, ScoreFeedback
from app.utils.datetime import to_iso_z, utcnow_naive


def stable_event_id(event_key: str) -> str:
    """Return a stable compact event id for a semantic event key."""

    normalized = str(event_key or "").strip()
    if not normalized:
        normalized = "unknown"
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:24]


def _source_names(items: Iterable[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for item in items:
        name = str(item.get("source_name") or "Unknown").strip()
        if name and name not in names:
            names.append(name)
    return names


def _event_times(items: Iterable[dict[str, Any]]) -> tuple[datetime | None, datetime | None]:
    times: list[datetime] = []
    for item in items:
        for key in ("publish_time", "fetched_at"):
            value = item.get(key)
            if isinstance(value, datetime):
                times.append(value)
                break
    if not times:
        return None, None
    return min(times), max(times)


def _snapshot_text(primary: dict[str, Any], cluster: dict[str, Any]) -> tuple[str, str | None, str | None, str | None]:
    title = str(primary.get("translated_title") or primary.get("title") or cluster.get("topic") or "未命名事件").strip()
    summary = str(primary.get("translated_summary") or primary.get("summary") or "").strip() or None
    why = None
    if int(cluster.get("independent_source_count") or 0) >= 2:
        why = "已有多个独立来源出现相近报道。"
    elif primary.get("lane") in {"must_read", "policy", "ai", "finance"}:
        why = "匹配高优先级主题，值得纳入今日重点。"
    what_changed = str(cluster.get("what_changed") or primary.get("new_signal") or "新来源或新版本进入事件簇。").strip()
    return title, summary, why, what_changed


def _content_ids(items: Iterable[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for item in items:
        cid = str(item.get("content_id") or "").strip()
        if cid and cid not in ids:
            ids.append(cid)
    return ids


def upsert_events_from_clusters(db: Session, clusters: list[dict[str, Any]]) -> list[ContentEvent]:
    """Persist Event/Membership/Snapshot rows from ranked clustering output."""

    persisted: list[ContentEvent] = []
    for cluster in clusters:
        items = [item for item in cluster.get("items") or [] if isinstance(item, dict)]
        if not items:
            continue
        event_key = str(cluster.get("event_key") or "").strip()
        if not event_key:
            continue
        event_id = stable_event_id(event_key)
        primary = items[0]
        title, summary, why_matters, what_changed = _snapshot_text(primary, cluster)
        first_seen, last_seen = _event_times(items)
        names = _source_names(items)
        source_content_ids = _content_ids(items)
        event = db.get(ContentEvent, event_id)
        if event is None:
            event = ContentEvent(
                event_id=event_id,
                event_key=event_key,
                title=title,
                summary=summary,
                status="active",
                first_seen_at=first_seen,
                created_at=utcnow_naive(),
            )
            db.add(event)
        event.title = title
        event.summary = summary
        event.last_seen_at = last_seen or event.last_seen_at
        if first_seen and (event.first_seen_at is None or first_seen < event.first_seen_at):
            event.first_seen_at = first_seen
        event.importance_score = float(cluster.get("event_score") or cluster.get("score") or 0.0)
        event.incremental_score = float(cluster.get("incremental_score") or 0.0)
        event.confidence_score = float(cluster.get("confidence_score") or 0.0)
        event.independent_source_count = int(cluster.get("independent_source_count") or len(names))
        event.source_names = names
        event.metadata_ = {
            "cluster_version": "hybrid-v0",
            "corroboration_tier": cluster.get("corroboration_tier"),
            "duplicate_group_is_article_level": True,
            "why_matters": why_matters,
            "what_changed": what_changed,
            "source_content_ids": source_content_ids,
        }
        event.updated_at = utcnow_naive()

        existing_members = {
            row.content_id
            for row in db.query(ContentEventMembership).filter(ContentEventMembership.event_id == event_id).all()
        }
        for idx, item in enumerate(items):
            cid = str(item.get("content_id") or "").strip()
            if not cid or cid in existing_members:
                continue
            db.add(
                ContentEventMembership(
                    event_id=event_id,
                    content_id=cid,
                    role="primary" if idx == 0 else "supporting",
                    confidence=float(cluster.get("corroboration") or 0.7),
                    evidence={
                        "event_key": event_key,
                        "duplicate_group_id": (item.get("metadata") or {}).get("duplicate_group_id")
                        if isinstance(item.get("metadata"), dict)
                        else None,
                        "reason": "hybrid_clusterer",
                    },
                    created_at=utcnow_naive(),
                )
            )
        latest_snapshot = (
            db.query(ContentEventSnapshot)
            .filter(ContentEventSnapshot.event_id == event_id)
            .order_by(ContentEventSnapshot.version.desc())
            .first()
        )
        latest_ids = set(latest_snapshot.source_content_ids or []) if latest_snapshot else set()
        current_ids = set(source_content_ids)
        should_create_snapshot = (
            latest_snapshot is None
            or latest_snapshot.title != title
            or latest_snapshot.summary != summary
            or latest_snapshot.what_changed != what_changed
            or latest_snapshot.why_matters != why_matters
            or latest_ids != current_ids
        )
        if should_create_snapshot:
            db.add(
                ContentEventSnapshot(
                    event_id=event_id,
                    version=(int(latest_snapshot.version) + 1) if latest_snapshot else 1,
                    title=title,
                    summary=summary,
                    what_changed=what_changed,
                    why_matters=why_matters,
                    source_content_ids=source_content_ids,
                    metadata_={"event_key": event_key, "source_names": names},
                    created_at=utcnow_naive(),
                )
            )
        persisted.append(event)
    return persisted


def event_row_to_card(row: ContentEvent, *, primary_content_id: str | None = None) -> dict[str, Any]:
    return {
        "event_id": row.event_id,
        "event_key": row.event_key,
        "title": row.title,
        "summary": row.summary,
        "why_matters": (row.metadata_ or {}).get("why_matters") or row.summary,
        "what_changed": (row.metadata_ or {}).get("what_changed") or "较上一版本出现新的来源或信息。",
        "independent_source_count": row.independent_source_count,
        "source_names": row.source_names or [],
        "updated_at": to_iso_z(row.last_seen_at or row.updated_at),
        "importance_score": row.importance_score,
        "confidence_score": row.confidence_score,
        "primary_content_id": primary_content_id,
    }


async def list_today_highlights(db: AsyncSession, target_date: date, *, limit: int = 8) -> list[dict[str, Any]]:
    """Return 3-8 event cards for the Digest page; empty means hide the section."""

    result = await db.execute(
        select(HourlyDigest)
        .where(HourlyDigest.digest_date == target_date)
        .order_by(HourlyDigest.hour.desc())
    )
    candidates: dict[str, dict[str, Any]] = {}
    for digest in result.scalars().all():
        for item in digest.items_json or []:
            if not isinstance(item, dict):
                continue
            section = str(item.get("section") or "").strip()
            if section not in {"need_to_know", "brewing"}:
                continue
            event_id = str(item.get("event_id") or "").strip()
            if not event_id:
                continue
            event_key = str(item.get("event_key") or "").strip()
            score = float(item.get("importance_score") or item.get("score") or 0.0)
            existing = candidates.get(event_id)
            if existing and float(existing.get("importance_score") or 0.0) >= score:
                continue
            candidates[event_id] = {
                "event_id": event_id,
                "event_key": event_key,
                "section": section,
                "title": item.get("title") or "未命名事件",
                "summary": item.get("summary") or item.get("what_happened"),
                "why_matters": item.get("why_matters"),
                "what_changed": item.get("new_signal") or item.get("what_happened"),
                "independent_source_count": item.get("independent_source_count") or len(item.get("source_names") or []),
                "source_names": item.get("source_names") or [item.get("source_name") or "Unknown"],
                "updated_at": item.get("fetched_at") or item.get("publish_time"),
                "importance_score": score,
                "confidence_score": item.get("confidence_score"),
                "primary_content_id": item.get("content_id"),
            }
    ordered = sorted(candidates.values(), key=lambda item: float(item.get("importance_score") or 0.0), reverse=True)
    qualified = [item for item in ordered if float(item.get("importance_score") or 0.0) >= 60]
    selected = qualified[: max(3, min(8, int(limit or 8)))] if len(qualified) >= 3 else []
    for item in selected:
        read_state = await get_event_read_state(db, str(item.get("event_id") or ""))
        item["latest_version"] = read_state.latest_version
        item["user_seen_version"] = read_state.user_seen_version
        item["has_updates"] = read_state.has_updates
    return selected


async def build_event_detail(db: AsyncSession, event_id: str) -> dict[str, Any] | None:
    event = await db.get(ContentEvent, event_id)
    if event is None:
        return None
    contents: list[Content] = []
    membership_result = await db.execute(
        select(ContentEventMembership).where(ContentEventMembership.event_id == event_id)
    )
    content_ids = [str(row.content_id) for row in membership_result.scalars().all()]
    if content_ids:
        content_result = await db.execute(
            select(Content)
            .options(selectinload(Content.source))
            .where(Content.id.in_(content_ids))
        )
        contents = list(content_result.scalars().all())
    contents.sort(key=lambda c: (c.publish_time or c.fetched_at or utcnow_naive(), str(c.id)))
    timeline = [
        {
            "content_id": str(content.id),
            "title": content.title,
            "summary": content.summary or content.translated_summary,
            "source_name": content.source.name if content.source else "Unknown",
            "url": content.original_url,
            "publish_time": to_iso_z(content.publish_time),
            "fetched_at": to_iso_z(content.fetched_at),
            "role": "primary" if idx == len(contents) - 1 else "supporting",
        }
        for idx, content in enumerate(contents)
    ]
    primary_reports = [item for item in timeline if item["role"] == "primary"] or timeline[-1:]
    independent_verification = [
        {
            "key": name,
            "title": name,
            "content_ids": [item["content_id"] for item in timeline if item["source_name"] == name],
        }
        for name in sorted({item["source_name"] for item in timeline})
    ]
    related_discussions = [
        {"key": "supporting", "title": "关联讨论", "content_ids": [item["content_id"] for item in timeline if item["role"] != "primary"]}
    ]

    snapshots_result = await db.execute(
        select(ContentEventSnapshot)
        .where(ContentEventSnapshot.event_id == event.event_id)
        .order_by(ContentEventSnapshot.version.desc())
        .limit(10)
    )
    snapshots = list(snapshots_result.scalars().all())
    read_state = await get_event_read_state(db, event.event_id)
    personal_state = await get_or_create_item_state(db, "event", event.event_id)
    feedback_result = await db.execute(
        select(ScoreFeedback)
        .where(ScoreFeedback.event_type.in_(["event_wrong_merge", "event_missing_merge"]))
        .order_by(ScoreFeedback.created_at.desc())
        .limit(20)
    )
    feedback = [row for row in feedback_result.scalars().all() if (row.snapshot or {}).get("event_id") == event.event_id]
    return {
        "event_id": event.event_id,
        "event_key": event.event_key,
        "title": event.title,
        "current_conclusion": event.summary or (contents[-1].summary if contents else None) or "该事件仍在观察中。",
        "why_matters": (snapshots[0].why_matters if snapshots else None) or (event.metadata_ or {}).get("why_matters"),
        "source_names": event.source_names or [c.source.name for c in contents if c.source],
        "independent_source_count": event.independent_source_count,
        "updated_at": to_iso_z(event.last_seen_at or event.updated_at),
        "latest_version": read_state.latest_version,
        "user_seen_version": read_state.user_seen_version,
        "has_updates": read_state.has_updates,
        "saved": bool(personal_state.saved),
        "read_later": bool(personal_state.read_later),
        "hidden": bool(personal_state.hidden),
        "timeline": timeline,
        "snapshots": [
            {
                "version": row.version,
                "title": row.title,
                "summary": row.summary,
                "what_changed": row.what_changed,
                "why_matters": row.why_matters,
                "created_at": to_iso_z(row.created_at),
                "is_seen": int(row.version or 0) <= read_state.user_seen_version,
            }
            for row in snapshots
        ],
        "primary_reports": primary_reports,
        "independent_verification": independent_verification,
        "related_discussions": related_discussions,
        "feedback": [
            {"type": row.event_type, "note": row.note, "created_at": to_iso_z(row.created_at)}
            for row in feedback
        ],
    }
