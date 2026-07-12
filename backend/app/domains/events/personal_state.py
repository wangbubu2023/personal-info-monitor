"""Personal event/report state and explicit rule workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Content,
    ContentEvent,
    ContentEventMembership,
    ContentEventSnapshot,
    InteractionEvent,
    ObservationAggregate,
    PersonalItemState,
    UserRule,
)
from app.utils.datetime import utcnow_naive

TargetType = Literal["report", "event"]
ScopeType = Literal["source", "topic", "entity", "event_type", "content_type"]

POSITIVE_ACTIONS = frozenset({"opened", "completed", "saved", "read_later"})
NEGATIVE_ACTIONS = frozenset({"hidden"})
SUGGESTION_MIN_SIGNALS = 3
SUGGESTION_CONFIDENCE = 0.72


@dataclass(frozen=True)
class EventReadState:
    latest_version: int
    user_seen_version: int
    has_updates: bool


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    return bool(value)


def _scope_from_content(content: Content | None) -> tuple[str | None, str | None]:
    if content is None:
        return None, None
    meta = content.metadata_ if isinstance(content.metadata_, dict) else {}
    lane = str(meta.get("lane") or getattr(content, "lane", None) or "").strip()
    if lane:
        return "topic", lane
    if content.source_id:
        return "source", str(content.source_id)
    content_type = str(content.content_type or "").strip()
    return ("content_type", content_type) if content_type else (None, None)


def _build_evidence_summary(aggregate: ObservationAggregate) -> str:
    pos = int(aggregate.positive_evidence_count or 0)
    neg = int(aggregate.negative_evidence_count or 0)
    if aggregate.suggested_rule == "mute":
        return f"最近对 {aggregate.scope_type}:{aggregate.scope_key} 有 {neg} 次隐藏/负向动作。"
    return f"最近对 {aggregate.scope_type}:{aggregate.scope_key} 有 {pos} 次保存/稍后读/阅读完成等正向动作。"


def _refresh_observation_suggestion(aggregate: ObservationAggregate) -> None:
    pos = int(aggregate.positive_evidence_count or 0)
    neg = int(aggregate.negative_evidence_count or 0)
    total = pos + neg
    if total <= 0:
        aggregate.confidence = 0.0
        aggregate.suggestion_status = "none"
        aggregate.suggested_rule = None
        aggregate.evidence_summary = None
        return

    majority = max(pos, neg)
    aggregate.confidence = round(majority / total, 3)
    if total >= SUGGESTION_MIN_SIGNALS and aggregate.confidence >= SUGGESTION_CONFIDENCE:
        aggregate.suggestion_status = "suggested"
        aggregate.suggested_rule = "mute" if neg > pos else "highlight"
        aggregate.evidence_summary = _build_evidence_summary(aggregate)
    elif aggregate.suggestion_status == "suggested":
        aggregate.suggestion_status = "none"
        aggregate.suggested_rule = None
        aggregate.evidence_summary = None


async def latest_event_version(db: AsyncSession, event_id: str) -> int:
    version = await db.scalar(
        select(ContentEventSnapshot.version)
        .where(ContentEventSnapshot.event_id == event_id)
        .order_by(ContentEventSnapshot.version.desc())
        .limit(1)
    )
    return int(version or 0)


async def get_or_create_item_state(db: AsyncSession, target_type: str, target_id: str) -> PersonalItemState:
    state = await db.scalar(
        select(PersonalItemState).where(
            PersonalItemState.target_type == target_type,
            PersonalItemState.target_id == target_id,
        )
    )
    if state is not None:
        return state
    state = PersonalItemState(target_type=target_type, target_id=target_id, created_at=utcnow_naive(), updated_at=utcnow_naive())
    db.add(state)
    await db.flush()
    return state


async def get_event_read_state(db: AsyncSession, event_id: str) -> EventReadState:
    latest = await latest_event_version(db, event_id)
    state = await db.scalar(
        select(PersonalItemState).where(
            PersonalItemState.target_type == "event",
            PersonalItemState.target_id == event_id,
        )
    )
    seen = int(state.last_seen_version or 0) if state else 0
    return EventReadState(latest_version=latest, user_seen_version=seen, has_updates=latest > seen)


async def record_interaction(
    db: AsyncSession,
    *,
    target_type: str,
    target_id: str,
    action: str,
    action_value: Any = True,
    content: Content | None = None,
    event: ContentEvent | None = None,
    event_version: int | None = None,
    scope_type: str | None = None,
    scope_key: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> InteractionEvent:
    if scope_type is None or scope_key is None:
        scope_type, scope_key = _scope_from_content(content)

    row = InteractionEvent(
        target_type=target_type,
        target_id=target_id,
        action=action,
        action_value=action_value,
        content_id=str(content.id) if content is not None else None,
        event_id=event.event_id if event is not None else (target_id if target_type == "event" else None),
        event_version=event_version,
        source_id=str(content.source_id) if content is not None and content.source_id else None,
        scope_type=scope_type,
        scope_key=scope_key,
        evidence=evidence or {},
        created_at=utcnow_naive(),
    )
    db.add(row)

    if scope_type and scope_key and _bool_value(action_value):
        aggregate = await db.scalar(
            select(ObservationAggregate).where(
                ObservationAggregate.scope_type == scope_type,
                ObservationAggregate.scope_key == scope_key,
            )
        )
        if aggregate is None:
            aggregate = ObservationAggregate(
                scope_type=scope_type,
                scope_key=scope_key,
                created_at=utcnow_naive(),
                updated_at=utcnow_naive(),
                metadata_={},
            )
            db.add(aggregate)
        if action in POSITIVE_ACTIONS:
            aggregate.positive_evidence_count = int(aggregate.positive_evidence_count or 0) + 1
        elif action in NEGATIVE_ACTIONS:
            aggregate.negative_evidence_count = int(aggregate.negative_evidence_count or 0) + 1
        aggregate.recent_activity_at = utcnow_naive()
        aggregate.updated_at = utcnow_naive()
        _refresh_observation_suggestion(aggregate)

    return row


async def mark_event_seen(db: AsyncSession, event_id: str, *, version: int | None = None) -> PersonalItemState:
    event = await db.get(ContentEvent, event_id)
    if event is None:
        raise ValueError("event not found")
    latest = version if version is not None else await latest_event_version(db, event_id)
    state = await get_or_create_item_state(db, "event", event_id)
    state.last_seen_version = max(int(state.last_seen_version or 0), int(latest or 0))
    state.read_at = utcnow_naive()
    state.updated_at = utcnow_naive()
    await record_interaction(
        db,
        target_type="event",
        target_id=event_id,
        action="completed",
        action_value=True,
        event=event,
        event_version=state.last_seen_version,
        scope_type="event_type",
        scope_key=str((event.metadata_ or {}).get("corroboration_tier") or event.status or "active"),
        evidence={"event_key": event.event_key, "source": "event.mark-seen"},
    )
    return state


async def update_event_state(
    db: AsyncSession,
    event_id: str,
    *,
    saved: bool | None = None,
    read_later: bool | None = None,
    hidden: bool | None = None,
) -> PersonalItemState:
    event = await db.get(ContentEvent, event_id)
    if event is None:
        raise ValueError("event not found")
    state = await get_or_create_item_state(db, "event", event_id)
    event_version = await latest_event_version(db, event_id)
    updates = {"saved": saved, "read_later": read_later, "hidden": hidden}
    for field, value in updates.items():
        if value is None:
            continue
        setattr(state, field, bool(value))
        action = "saved" if field == "saved" else field
        await record_interaction(
            db,
            target_type="event",
            target_id=event_id,
            action=action,
            action_value=bool(value),
            event=event,
            event_version=event_version,
            scope_type="event_type",
            scope_key=str((event.metadata_ or {}).get("corroboration_tier") or event.status or "active"),
            evidence={"event_key": event.event_key, "source": "event.state"},
        )
    state.updated_at = utcnow_naive()
    return state


async def record_report_interaction_from_content(
    db: AsyncSession,
    content: Content,
    *,
    action: str,
    action_value: Any = True,
    evidence: dict[str, Any] | None = None,
) -> None:
    state = await get_or_create_item_state(db, "report", str(content.id))
    if action in {"opened", "completed"}:
        state.last_seen_version = max(int(state.last_seen_version or 0), 1)
        state.read_at = utcnow_naive()
    elif action == "saved":
        state.saved = bool(action_value)
    elif action == "read_later":
        state.read_later = bool(action_value)
    elif action == "hidden":
        state.hidden = bool(action_value)
    state.updated_at = utcnow_naive()

    membership = await db.scalar(select(ContentEventMembership).where(ContentEventMembership.content_id == str(content.id)))
    event = await db.get(ContentEvent, membership.event_id) if membership is not None else None
    event_id = event.event_id if event is not None else None
    event_version = await latest_event_version(db, event_id) if event_id else None
    await record_interaction(
        db,
        target_type="report",
        target_id=str(content.id),
        action=action,
        action_value=action_value,
        content=content,
        event=event,
        event_version=event_version,
        evidence={"event_id": event_id, **(evidence or {})},
    )


async def list_suggested_observations(db: AsyncSession, *, limit: int = 50) -> list[ObservationAggregate]:
    result = await db.execute(
        select(ObservationAggregate)
        .where(ObservationAggregate.suggestion_status == "suggested")
        .order_by(ObservationAggregate.confidence.desc(), ObservationAggregate.recent_activity_at.desc().nulls_last())
        .limit(max(1, min(200, int(limit))))
    )
    return list(result.scalars().all())


async def accept_observation_suggestion(db: AsyncSession, observation_id: int) -> UserRule:
    aggregate = await db.get(ObservationAggregate, observation_id)
    if aggregate is None or aggregate.suggestion_status != "suggested" or not aggregate.suggested_rule:
        raise ValueError("suggestion not found")
    existing = await db.scalar(
        select(UserRule).where(
            UserRule.scope_type == aggregate.scope_type,
            UserRule.scope_key == aggregate.scope_key,
            UserRule.status == "active",
        )
    )
    if existing is not None:
        existing.rule = aggregate.suggested_rule
        existing.created_by = "accepted_suggestion"
        existing.evidence_summary = aggregate.evidence_summary
        existing.metadata_ = {**(existing.metadata_ or {}), "observation_id": aggregate.id, "confidence": aggregate.confidence}
        existing.updated_at = utcnow_naive()
        aggregate.suggestion_status = "accepted"
        aggregate.updated_at = utcnow_naive()
        return existing
    rule = UserRule(
        scope_type=aggregate.scope_type,
        scope_key=aggregate.scope_key,
        rule=aggregate.suggested_rule,
        status="active",
        created_by="accepted_suggestion",
        evidence_summary=aggregate.evidence_summary,
        metadata_={"observation_id": aggregate.id, "confidence": aggregate.confidence},
        created_at=utcnow_naive(),
        updated_at=utcnow_naive(),
    )
    db.add(rule)
    aggregate.suggestion_status = "accepted"
    aggregate.updated_at = utcnow_naive()
    await db.flush()
    return rule


async def dismiss_observation_suggestion(db: AsyncSession, observation_id: int) -> ObservationAggregate:
    aggregate = await db.get(ObservationAggregate, observation_id)
    if aggregate is None:
        raise ValueError("suggestion not found")
    aggregate.suggestion_status = "dismissed"
    aggregate.updated_at = utcnow_naive()
    return aggregate
