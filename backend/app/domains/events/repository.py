"""Repository helpers for stable Event v0.

The first production slice is deliberately deterministic and DB-light:
``RankingService`` still performs the hybrid clustering inside the hourly
pipeline, then this repository persists stable event identities and membership
snapshots. Duplicate groups remain article-level facts and are only used as one
possible clustering signal.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.session import Session

from app.domains.events.personal_state import get_event_read_state, get_or_create_item_state
from app.domains.events.presentation import (
    NEED_TO_KNOW_IMPORTANCE_THRESHOLD,
    TODAY_HIGHLIGHT_MIN_INDEPENDENT_SOURCES,
    TODAY_HIGHLIGHT_WINDOW_HOURS,
    event_name_from_cluster,
)
from app.models import (
    Content,
    ContentEvent,
    ContentEventMembership,
    ContentEventSnapshot,
    EventAlias,
    EventAssignmentLog,
    EventMembershipV1,
    EventOperation,
    ScoreFeedback,
    UserRule,
)
from app.utils.datetime import to_iso_z, user_timezone, utcnow_naive


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
    title = event_name_from_cluster(primary, cluster)
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
            event.latest_snapshot_version = (int(latest_snapshot.version) + 1) if latest_snapshot else 1
        for item in items:
            cid = str(item.get("content_id") or "").strip()
            if not cid:
                continue
            logged = (
                db.query(EventAssignmentLog.id)
                .filter(
                    EventAssignmentLog.content_id == cid,
                    EventAssignmentLog.assignment_version == "hybrid-v0",
                )
                .first()
            )
            if logged is None:
                db.add(
                    EventAssignmentLog(
                        content_id=cid,
                        assignment_version="hybrid-v0",
                        selected_event_id=event_id,
                        decision="attach",
                        relation="same_event",
                        assignment_method="hourly_hybrid_clusterer",
                        candidate_count=0,
                        candidates=[],
                        component_scores=cluster.get("component_scores") or {},
                        hard_conflicts=[],
                        explain_reasons=cluster.get("explain_reasons") or [],
                        effective_threshold=(cluster.get("similarity_thresholds") or {}).get("default"),
                        latency_ms=0.0,
                        shadow_only=False,
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


async def _apply_active_user_rules(db: AsyncSession, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply explicit monitor rules to event cards without changing global scores.

    Natural interactions only create suggestions. Once a user accepts or creates
    a rule, it affects their event highlights: ``mute`` hides matching cards,
    ``quiet`` de-prioritises them, and ``highlight`` / ``notify`` promote them.
    ``notify`` is exposed to the client so its delivery surface can decide how
    to alert without altering the event's shared score.
    """
    if not candidates:
        return []

    rules_result = await db.execute(select(UserRule).where(UserRule.status == "active"))
    rules = list(rules_result.scalars().all())
    if not rules:
        return candidates

    content_ids = {
        str(content_id)
        for item in candidates
        for content_id in item.get("content_ids") or [item.get("primary_content_id")]
        if content_id
    }
    content_scopes: dict[str, set[tuple[str, str]]] = {}
    if content_ids:
        content_result = await db.execute(
            select(Content.id, Content.source_id, Content.content_type, Content.lane, Content.metadata_).where(
                Content.id.in_(content_ids)
            )
        )
        for content_id, source_id, content_type, lane, metadata in content_result.all():
            scopes: set[tuple[str, str]] = set()
            if source_id:
                scopes.add(("source", str(source_id)))
            content_metadata = metadata if isinstance(metadata, dict) else {}
            resolved_lane = str(lane or content_metadata.get("lane") or "").strip()
            if resolved_lane:
                scopes.add(("topic", resolved_lane))
            if content_type:
                scopes.add(("content_type", str(content_type)))
            content_scopes[str(content_id)] = scopes

    priority = {"quiet": -1, "highlight": 1, "notify": 2}
    filtered: list[dict[str, Any]] = []
    for item in candidates:
        scopes = {
            ("event", str(item.get("event_id") or "")),
            ("event_type", str(item.get("corroboration_tier") or "")),
        }
        for content_id in item.get("content_ids") or [item.get("primary_content_id")]:
            scopes.update(content_scopes.get(str(content_id), set()))
        scopes.discard(("event", ""))
        scopes.discard(("event_type", ""))

        matching = [rule.rule for rule in rules if (rule.scope_type, rule.scope_key) in scopes]
        if "mute" in matching:
            continue
        effective_rule = max(matching, key=lambda rule: priority.get(rule, 0), default=None)
        if effective_rule:
            item["personal_rule"] = effective_rule
            item["notification_requested"] = effective_rule == "notify"
        item["_rule_priority"] = priority.get(effective_rule or "", 0)
        filtered.append(item)
    return filtered


def _rolling_highlight_window(target_date: date) -> tuple[datetime, datetime]:
    """Return the UTC-naive 48-hour window ending at the selected local date."""

    tz = user_timezone()
    now_local = datetime.now(tz)
    if target_date >= now_local.date():
        end_local = now_local
    else:
        end_local = datetime.combine(target_date + timedelta(days=1), time.min, tzinfo=tz)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return end_utc - timedelta(hours=TODAY_HIGHLIGHT_WINDOW_HOURS), end_utc


async def list_today_highlights(db: AsyncSession, target_date: date, *, limit: int = 50) -> list[dict[str, Any]]:
    """Return hot, sufficiently corroborated persisted Events from a rolling 48-hour window."""

    from app.domains.events.config import event_config, event_v1_today_read_enabled

    cluster_version = event_config().cluster_version if event_v1_today_read_enabled() else "hybrid-v0"
    window_start, window_end = _rolling_highlight_window(target_date)
    activity_at = func.coalesce(
        ContentEvent.last_material_update_at,
        ContentEvent.last_seen_at,
        ContentEvent.updated_at,
    )
    result = await db.execute(
        select(ContentEvent)
        .where(
            ContentEvent.cluster_version == cluster_version,
            ContentEvent.status.in_(["active", "cooling", "reopened"]),
            activity_at >= window_start,
            activity_at < window_end,
            ContentEvent.importance_score >= NEED_TO_KNOW_IMPORTANCE_THRESHOLD,
            ContentEvent.independent_source_count >= TODAY_HIGHLIGHT_MIN_INDEPENDENT_SOURCES,
        )
        .order_by(
            ContentEvent.importance_score.desc(),
            activity_at.desc(),
            ContentEvent.event_id,
        )
        .limit(max(1, min(50, int(limit or 50))))
    )
    candidates: list[dict[str, Any]] = []
    for event in result.scalars().all():
        snapshot_result = await db.execute(
            select(ContentEventSnapshot)
            .where(ContentEventSnapshot.event_id == event.event_id)
            .order_by(ContentEventSnapshot.version.desc())
            .limit(1)
        )
        snapshot = snapshot_result.scalar_one_or_none()
        explanation = snapshot.explanation if snapshot and isinstance(snapshot.explanation, dict) else {}
        primary_content_id = (
            str(snapshot.canonical_content_id or event.canonical_content_id or "")
            if snapshot
            else str(event.canonical_content_id or "")
        ) or None
        content_ids = list(snapshot.source_content_ids or []) if snapshot else []
        candidates.append(
            {
                "event_id": event.event_id,
                "event_key": event.event_key,
                "section": "need_to_know",
                "title": snapshot.title if snapshot else event.title,
                "summary": snapshot.summary if snapshot else event.summary,
                "why_matters": (
                    explanation.get("selection_reason")
                    or (snapshot.why_matters if snapshot else None)
                    or (event.metadata_ or {}).get("why_matters")
                    or event.summary
                ),
                "what_changed": (
                    explanation.get("what_changed_since_last_read")
                    or (snapshot.what_changed if snapshot else None)
                    or (event.metadata_ or {}).get("what_changed")
                ),
                "independent_source_count": int(event.independent_source_count or 0),
                "source_names": event.source_names or [],
                "updated_at": to_iso_z(
                    event.last_material_update_at or event.last_seen_at or event.updated_at
                ),
                "importance_score": event.importance_score,
                "confidence_score": event.confidence_score,
                "primary_content_id": primary_content_id,
                "snapshot_version": int(snapshot.version if snapshot else event.latest_snapshot_version or 0),
                "content_ids": content_ids or ([primary_content_id] if primary_content_id else []),
                "corroboration_tier": (event.metadata_ or {}).get("corroboration_tier"),
            }
        )

    rule_adjusted = await _apply_active_user_rules(db, candidates)
    ordered = sorted(
        rule_adjusted,
        key=lambda item: (int(item.get("_rule_priority") or 0), float(item.get("importance_score") or 0.0)),
        reverse=True,
    )
    selected = ordered[: min(50, int(limit or 50))]
    for item in selected:
        read_state = await get_event_read_state(db, str(item.get("event_id") or ""))
        item["latest_version"] = read_state.latest_version
        item["user_seen_version"] = read_state.user_seen_version
        item["has_updates"] = read_state.has_updates
        item.pop("_rule_priority", None)
    return selected


async def build_event_detail(
    db: AsyncSession,
    event_id: str,
    *,
    full_reports: bool = False,
) -> dict[str, Any] | None:
    event = await db.get(ContentEvent, event_id)
    if event is None:
        return None
    contents: list[Content] = []
    if event.cluster_version != "hybrid-v0":
        membership_result = await db.execute(
            select(EventMembershipV1).where(
                EventMembershipV1.event_id == event_id,
                EventMembershipV1.active.is_(True),
            )
        )
    else:
        membership_result = await db.execute(
            select(ContentEventMembership).where(ContentEventMembership.event_id == event_id)
        )
    membership_rows = list(membership_result.scalars().all())
    content_ids = [str(row.content_id) for row in membership_rows]
    membership_roles = {str(row.content_id): str(row.role) for row in membership_rows}
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
            "role": membership_roles.get(str(content.id), "primary" if idx == len(contents) - 1 else "supporting"),
        }
        for idx, content in enumerate(contents)
    ]
    if full_reports:
        visible_timeline = timeline
    else:
        selected_ids: set[str] = set()
        for item in [
            *(row for row in reversed(timeline) if row["role"] == "primary"),
            *reversed(timeline),
        ]:
            selected_ids.add(item["content_id"])
            if len(selected_ids) >= 3:
                break
        visible_timeline = [item for item in timeline if item["content_id"] in selected_ids]
    primary_reports = [item for item in visible_timeline if item["role"] == "primary"] or visible_timeline[-1:]
    independent_verification = [
        {
            "key": name,
            "title": name,
            "content_ids": [item["content_id"] for item in visible_timeline if item["source_name"] == name],
        }
        for name in sorted({item["source_name"] for item in visible_timeline})
    ]
    related_discussions = [
        {"key": "supporting", "title": "关联讨论", "content_ids": [item["content_id"] for item in visible_timeline if item["role"] != "primary"]}
    ]

    snapshots_result = await db.execute(
        select(ContentEventSnapshot)
        .where(ContentEventSnapshot.event_id == event.event_id)
        .order_by(ContentEventSnapshot.version.desc())
        .limit(10)
    )
    snapshots = list(snapshots_result.scalars().all())
    canonical_snapshot = snapshots[0] if snapshots else None
    read_state = await get_event_read_state(db, event.event_id)
    personal_state = await get_or_create_item_state(db, "event", event.event_id)
    feedback_result = await db.execute(
        select(ScoreFeedback)
        .where(ScoreFeedback.event_type.in_(["event_wrong_merge", "event_missing_merge"]))
        .order_by(ScoreFeedback.created_at.desc())
        .limit(20)
    )
    feedback = [row for row in feedback_result.scalars().all() if (row.snapshot or {}).get("event_id") == event.event_id]
    operations_result = await db.execute(
        select(EventOperation)
        .where(EventOperation.event_id == event.event_id)
        .order_by(EventOperation.created_at.desc())
        .limit(50)
    )
    operations = list(operations_result.scalars().all())
    aliases_result = await db.execute(
        select(EventAlias).where(EventAlias.canonical_event_id == event.event_id)
    )
    aliases = list(aliases_result.scalars().all())
    return {
        "event_id": event.event_id,
        "event_key": event.event_key,
        "title": canonical_snapshot.title if canonical_snapshot else event.title,
        "current_conclusion": (
            (canonical_snapshot.summary if canonical_snapshot else None)
            or event.summary
            or (contents[-1].summary if contents else None)
            or "该事件仍在观察中。"
        ),
        "why_matters": (canonical_snapshot.why_matters if canonical_snapshot else None) or (event.metadata_ or {}).get("why_matters"),
        "source_names": event.source_names or [c.source.name for c in contents if c.source],
        "independent_source_count": event.independent_source_count,
        "updated_at": to_iso_z(event.last_seen_at or event.updated_at),
        "latest_version": read_state.latest_version,
        "user_seen_version": read_state.user_seen_version,
        "has_updates": read_state.has_updates,
        "saved": bool(personal_state.saved),
        "read_later": bool(personal_state.read_later),
        "hidden": bool(personal_state.hidden),
        "timeline": visible_timeline,
        "snapshots": [
            {
                "version": row.version,
                "title": row.title,
                "summary": row.summary,
                "what_changed": row.what_changed,
                "why_matters": row.why_matters,
                "created_at": to_iso_z(row.created_at),
                "is_seen": int(row.version or 0) <= read_state.user_seen_version,
                "change_type": row.change_type,
                "facts": row.facts or [],
                "evidence_refs": row.evidence_refs or [],
                "uncertainty": row.uncertainty or [],
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
        "extra": dict(
            view_mode="full" if full_reports else "curated",
            report_count=len(timeline),
            cluster_version=event.cluster_version,
            event_state=event.event_state,
            status=event.status,
            canonical_content_id=str(event.canonical_content_id or "") or None,
            dispersion=event.dispersion,
            centroid_version=(event.centroid or {}).get("centroid_version"),
            source_independence=(event.metadata_ or {}).get("source_independence") or {},
            aliases=[
                {
                    "type": row.alias_type,
                    "value": row.alias_value,
                    "redirect_enabled": bool(row.redirect_enabled),
                }
                for row in aliases
            ],
            operations=[
                {
                    "id": str(row.id),
                    "type": row.operation_type,
                    "input_event_ids": row.input_event_ids or [],
                    "output_event_ids": row.output_event_ids or [],
                    "reason": row.reason,
                    "actor": row.actor,
                    "created_at": to_iso_z(row.created_at),
                }
                for row in operations
            ],
        ),
    }
