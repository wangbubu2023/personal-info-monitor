"""Event v0 HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_async_db
from app.domains.events.personal_state import mark_event_seen, update_event_state
from app.domains.events.repository import build_event_detail, list_today_highlights
from app.domains.score.feedback import content_feedback_snapshot, record_score_feedback_event
from app.models import Content
from app.schemas.events import EventDetailResponse, EventFeedbackCreate, EventFeedbackItem, TodayHighlightsResponse
from app.schemas.personal_monitor import EventStateUpdate, PersonalItemStateResponse
from app.utils.datetime import to_iso_z, today_in_user_timezone

router = APIRouter()

_VALID_EVENT_FEEDBACK = frozenset({"event_wrong_merge", "event_missing_merge"})


def _personal_state_response(state) -> PersonalItemStateResponse:
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


@router.get("/today-highlights", response_model=TodayHighlightsResponse)
async def get_today_highlights(
    digest_date: Optional[str] = Query(None, alias="date"),
    limit: int = Query(8, ge=3, le=8),
    db: AsyncSession = Depends(get_async_db),
):
    """Return 3-8 event cards for the PIM Digest page.

    Empty ``items`` means the section should be hidden. The Timeline/资讯 page
    intentionally keeps the full content timeline and does not consume this API.
    """

    target_date = datetime.strptime(digest_date, "%Y-%m-%d").date() if digest_date else today_in_user_timezone()
    items = await list_today_highlights(db, target_date, limit=limit)
    return TodayHighlightsResponse(date=target_date.isoformat(), items=items)


@router.get("/{event_id}", response_model=EventDetailResponse)
async def get_event_detail(event_id: str, db: AsyncSession = Depends(get_async_db)):
    detail = await build_event_detail(db, event_id.strip())
    if not detail:
        raise HTTPException(status_code=404, detail="Event not found")
    return EventDetailResponse(**detail)


@router.post("/{event_id}/seen", response_model=PersonalItemStateResponse)
async def mark_event_as_seen(event_id: str, db: AsyncSession = Depends(get_async_db)):
    try:
        state = await mark_event_seen(db, event_id.strip())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(state)
    return _personal_state_response(state)


@router.patch("/{event_id}/state", response_model=PersonalItemStateResponse)
async def patch_event_state(event_id: str, body: EventStateUpdate, db: AsyncSession = Depends(get_async_db)):
    try:
        state = await update_event_state(
            db,
            event_id.strip(),
            saved=body.saved,
            read_later=body.read_later,
            hidden=body.hidden,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(state)
    return _personal_state_response(state)


@router.post("/{event_id}/feedback", response_model=EventFeedbackItem)
async def create_event_feedback(
    event_id: str,
    body: EventFeedbackCreate,
    db: AsyncSession = Depends(get_async_db),
):
    feedback_type = body.type.strip()
    if feedback_type not in _VALID_EVENT_FEEDBACK:
        raise HTTPException(status_code=400, detail="Invalid event feedback type")
    content = None
    if body.content_id:
        content = (
            await db.execute(
                select(Content).options(selectinload(Content.source)).where(Content.id == str(UUID(body.content_id)))
            )
        ).scalar_one_or_none()
    if content is None:
        detail = await build_event_detail(db, event_id.strip())
        first_content_id = (detail or {}).get("timeline", [{}])[0].get("content_id") if detail else None
        if first_content_id:
            content = (
                await db.execute(
                    select(Content).options(selectinload(Content.source)).where(Content.id == str(UUID(first_content_id)))
                )
            ).scalar_one_or_none()
    if content is None:
        raise HTTPException(status_code=404, detail="Feedback anchor content not found")

    row = await record_score_feedback_event(
        db,
        content,
        event_type=feedback_type,
        event_value={"event_id": event_id.strip()},
        note=(body.note or "").strip() or None,
        snapshot=content_feedback_snapshot(content, {"event_id": event_id.strip(), "source": "events.feedback"}),
    )
    await db.commit()
    await db.refresh(row)
    return EventFeedbackItem(type=row.event_type or feedback_type, note=row.note, created_at=row.created_at.isoformat())
