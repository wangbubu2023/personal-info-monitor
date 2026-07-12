"""Personal monitor state HTTP API."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.domains.events.personal_state import (
    accept_observation_suggestion,
    dismiss_observation_suggestion,
    get_event_read_state,
    get_or_create_item_state,
    list_suggested_observations,
    record_report_interaction_from_content,
)
from app.models import Content, ContentEvent, UserRule
from app.schemas.personal_monitor import (
    EventReadStateResponse,
    ObservationAggregateResponse,
    PersonalItemStateResponse,
    ReportStateUpdate,
    UserRuleCreate,
    UserRuleResponse,
    UserRuleUpdate,
)
from app.utils.datetime import to_iso_z, utcnow_naive

router = APIRouter()
_VALID_RULES = frozenset({"highlight", "normal", "quiet", "notify", "mute"})
_VALID_RULE_STATUS = frozenset({"active", "paused", "revoked"})


def _state_response(state) -> PersonalItemStateResponse:
    return PersonalItemStateResponse(
        target_type=state.target_type,
        target_id=state.target_id,
        last_seen_version=int(state.last_seen_version or 0),
        saved=bool(state.saved),
        read_later=bool(state.read_later),
        hidden=bool(state.hidden),
        read_at=to_iso_z(state.read_at),
        updated_at=to_iso_z(state.updated_at),
    )


def _observation_response(row) -> ObservationAggregateResponse:
    return ObservationAggregateResponse(
        id=row.id,
        scope_type=row.scope_type,
        scope_key=row.scope_key,
        positive_evidence_count=int(row.positive_evidence_count or 0),
        negative_evidence_count=int(row.negative_evidence_count or 0),
        confidence=float(row.confidence or 0.0),
        suggestion_status=row.suggestion_status,
        suggested_rule=row.suggested_rule,
        evidence_summary=row.evidence_summary,
        recent_activity_at=to_iso_z(row.recent_activity_at),
        metadata=row.metadata_ or {},
    )


def _rule_response(row: UserRule) -> UserRuleResponse:
    return UserRuleResponse(
        id=str(row.id),
        scope_type=row.scope_type,
        scope_key=row.scope_key,
        rule=row.rule,
        status=row.status,
        created_by=row.created_by,
        evidence_summary=row.evidence_summary,
        metadata=row.metadata_ or {},
        created_at=to_iso_z(row.created_at),
        updated_at=to_iso_z(row.updated_at),
    )


@router.get("/states/{target_type}/{target_id}", response_model=PersonalItemStateResponse)
async def get_personal_state(target_type: str, target_id: str, db: AsyncSession = Depends(get_async_db)):
    if target_type not in {"report", "event"}:
        raise HTTPException(status_code=400, detail="Invalid target type")
    state = await get_or_create_item_state(db, target_type, target_id.strip())
    await db.commit()
    return _state_response(state)


@router.get("/events/{event_id}/read-state", response_model=EventReadStateResponse)
async def get_event_personal_read_state(event_id: str, db: AsyncSession = Depends(get_async_db)):
    normalized_event_id = event_id.strip()
    if await db.get(ContentEvent, normalized_event_id) is None:
        raise HTTPException(status_code=404, detail="Event not found")
    read_state = await get_event_read_state(db, normalized_event_id)
    state = await get_or_create_item_state(db, "event", normalized_event_id)
    await db.commit()
    return EventReadStateResponse(
        event_id=normalized_event_id,
        latest_version=read_state.latest_version,
        user_seen_version=read_state.user_seen_version,
        has_updates=read_state.has_updates,
        state=_state_response(state),
    )


@router.patch("/reports/{content_id}/state", response_model=PersonalItemStateResponse)
async def patch_report_state(content_id: str, body: ReportStateUpdate, db: AsyncSession = Depends(get_async_db)):
    content = await db.get(Content, content_id.strip())
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")
    if body.completed is not None:
        await record_report_interaction_from_content(
            db,
            content,
            action="completed",
            action_value=body.completed,
            evidence={"source": "personal-monitor.report-state"},
        )
    if body.saved is not None:
        await record_report_interaction_from_content(
            db,
            content,
            action="saved",
            action_value=body.saved,
            evidence={"source": "personal-monitor.report-state"},
        )
    if body.read_later is not None:
        await record_report_interaction_from_content(
            db,
            content,
            action="read_later",
            action_value=body.read_later,
            evidence={"source": "personal-monitor.report-state"},
        )
    if body.hidden is not None:
        await record_report_interaction_from_content(
            db,
            content,
            action="hidden",
            action_value=body.hidden,
            evidence={"source": "personal-monitor.report-state"},
        )
    state = await get_or_create_item_state(db, "report", content_id.strip())
    await db.commit()
    await db.refresh(state)
    return _state_response(state)


@router.get("/observations/suggestions", response_model=list[ObservationAggregateResponse])
async def list_observation_suggestions(limit: int = Query(50, ge=1, le=200), db: AsyncSession = Depends(get_async_db)):
    rows = await list_suggested_observations(db, limit=limit)
    return [_observation_response(row) for row in rows]


@router.post("/observations/{observation_id}/accept", response_model=UserRuleResponse)
async def accept_observation(observation_id: int, db: AsyncSession = Depends(get_async_db)):
    try:
        rule = await accept_observation_suggestion(db, observation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(rule)
    return _rule_response(rule)


@router.post("/observations/{observation_id}/dismiss", response_model=ObservationAggregateResponse)
async def dismiss_observation(observation_id: int, db: AsyncSession = Depends(get_async_db)):
    try:
        row = await dismiss_observation_suggestion(db, observation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(row)
    return _observation_response(row)


@router.get("/rules", response_model=list[UserRuleResponse])
async def list_user_rules(
    status: Optional[str] = Query(None),
    rule: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_db),
):
    query = select(UserRule).order_by(UserRule.updated_at.desc())
    if status:
        query = query.where(UserRule.status == status)
    if rule:
        query = query.where(UserRule.rule == rule)
    result = await db.execute(query)
    return [_rule_response(row) for row in result.scalars().all()]


@router.post("/rules", response_model=UserRuleResponse)
async def create_user_rule(body: UserRuleCreate, db: AsyncSession = Depends(get_async_db)):
    if body.rule not in _VALID_RULES:
        raise HTTPException(status_code=400, detail="Invalid rule")
    row = UserRule(
        scope_type=body.scope_type.strip(),
        scope_key=body.scope_key.strip(),
        rule=body.rule,
        status="active",
        created_by="user",
        evidence_summary=(body.evidence_summary or "").strip() or None,
        metadata_=body.metadata or {},
        created_at=utcnow_naive(),
        updated_at=utcnow_naive(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _rule_response(row)


@router.patch("/rules/{rule_id}", response_model=UserRuleResponse)
async def update_user_rule(rule_id: str, body: UserRuleUpdate, db: AsyncSession = Depends(get_async_db)):
    row = await db.get(UserRule, rule_id.strip())
    if row is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    if body.rule is not None:
        if body.rule not in _VALID_RULES:
            raise HTTPException(status_code=400, detail="Invalid rule")
        row.rule = body.rule
    if body.status is not None:
        if body.status not in _VALID_RULE_STATUS:
            raise HTTPException(status_code=400, detail="Invalid rule status")
        row.status = body.status
    if body.evidence_summary is not None:
        row.evidence_summary = body.evidence_summary.strip() or None
    if body.metadata is not None:
        row.metadata_ = body.metadata
    row.updated_at = utcnow_naive()
    await db.commit()
    await db.refresh(row)
    return _rule_response(row)


@router.delete("/rules/{rule_id}", response_model=UserRuleResponse)
async def revoke_user_rule(rule_id: str, db: AsyncSession = Depends(get_async_db)):
    row = await db.get(UserRule, rule_id.strip())
    if row is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    row.status = "revoked"
    row.updated_at = utcnow_naive()
    await db.commit()
    await db.refresh(row)
    return _rule_response(row)
