"""Event v0 HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import features
from app.database import get_async_db
from app.domains.eval.annotation_recording import (
    AnnotationTaskImmutableError,
    record_annotation_label,
)
from app.domains.events.personal_state import mark_event_seen, update_event_state
from app.domains.events.repository import build_event_detail, list_today_highlights
from app.domains.score.feedback import (
    EVENT_CLUSTER_FEEDBACK_EVENTS,
    adjudicate_quality_feedback,
    content_feedback_snapshot,
    record_score_feedback_event,
)
from app.models import (
    Content,
    EventAssignmentLog,
    EventMembershipV1,
    EventOperation,
    EventRebalanceRun,
    EventRebalanceSuggestion,
    EventSignature,
    QualityAdjudication,
    ScoreFeedback,
)
from app.schemas.events import (
    EventDetailResponse,
    EventFeedbackCreate,
    EventFeedbackItem,
    EventLifecycleCreate,
    EventMergeCreate,
    EventRebalanceCreate,
    EventRevertCreate,
    EventSplitCreate,
    QualityAdjudicationCreate,
    QualityAdjudicationItem,
    QualityFeedbackQueueItem,
    TodayHighlightsResponse,
)
from app.schemas.personal_monitor import EventStateUpdate, PersonalItemStateResponse
from app.utils.datetime import to_iso_z, today_in_user_timezone

router = APIRouter()

_VALID_EVENT_FEEDBACK = EVENT_CLUSTER_FEEDBACK_EVENTS


@router.get("/config")
async def get_event_engine_config():
    from app.domains.events.config import export_event_config

    return export_event_config()


@router.get("/resolve/{event_ref}")
async def resolve_event_reference(event_ref: str, db: AsyncSession = Depends(get_async_db)):
    from app.domains.events.operations import resolve_event

    resolved = await db.run_sync(lambda session: resolve_event(session, event_ref.strip()))
    if resolved is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return resolved


@router.get("/diagnostics/content/{content_id}")
async def get_content_assignment_diagnostics(
    content_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_async_db),
):
    from app.domains.events.config import event_debug_explain_enabled

    if not event_debug_explain_enabled():
        raise HTTPException(status_code=404, detail="Event diagnostics disabled")
    logs = list(
        (
            await db.execute(
                select(EventAssignmentLog)
                .where(EventAssignmentLog.content_id == str(content_id))
                .order_by(EventAssignmentLog.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    )
    signatures = list(
        (
            await db.execute(
                select(EventSignature)
                .where(EventSignature.content_id == str(content_id))
                .order_by(EventSignature.created_at.desc())
            )
        ).scalars().all()
    )
    memberships = list(
        (
            await db.execute(
                select(EventMembershipV1)
                .where(EventMembershipV1.content_id == str(content_id))
                .order_by(EventMembershipV1.created_at.desc())
            )
        ).scalars().all()
    )
    return {
        "content_id": str(content_id),
        "signatures": [
            {
                "version": row.signature_version,
                "fingerprint": row.fingerprint,
                "confidence": row.confidence,
                "method": row.extraction_method,
                "model_version": row.model_version,
                "evidence_spans": row.evidence_spans or [],
            }
            for row in signatures
        ],
        "memberships": [
            {
                "event_id": row.event_id,
                "assignment_version": row.assignment_version,
                "active": bool(row.active),
                "relation": row.relation,
                "method": row.assignment_method,
                "confidence": row.confidence,
                "effective_threshold": row.effective_threshold,
            }
            for row in memberships
        ],
        "assignments": [
            {
                "id": str(row.id),
                "event_id": row.selected_event_id,
                "decision": row.decision,
                "relation": row.relation,
                "candidate_count": row.candidate_count,
                "candidates": row.candidates or [],
                "component_scores": row.component_scores or {},
                "hard_conflicts": row.hard_conflicts or [],
                "effective_threshold": row.effective_threshold,
                "latency_ms": row.latency_ms,
                "classifier_version": row.assignment_version,
                "shadow_only": bool(row.shadow_only),
                "created_at": to_iso_z(row.created_at),
            }
            for row in logs
        ],
    }


@router.get("/diagnostics/event/{event_id}")
async def get_event_diagnostics(event_id: str, db: AsyncSession = Depends(get_async_db)):
    from app.domains.events.config import event_debug_explain_enabled

    if not event_debug_explain_enabled():
        raise HTTPException(status_code=404, detail="Event diagnostics disabled")
    detail = await build_event_detail(db, event_id.strip())
    if not detail:
        raise HTTPException(status_code=404, detail="Event not found")
    suggestions = list(
        (
            await db.execute(
                select(EventRebalanceSuggestion)
                .where(EventRebalanceSuggestion.event_ids.contains(event_id.strip()))
                .order_by(EventRebalanceSuggestion.created_at.desc())
                .limit(50)
            )
        ).scalars().all()
    )
    return {
        "event_id": event_id.strip(),
        "cluster_version": (detail.get("extra") or {}).get("cluster_version"),
        "status": (detail.get("extra") or {}).get("status"),
        "dispersion": (detail.get("extra") or {}).get("dispersion"),
        "source_independence": (detail.get("extra") or {}).get("source_independence"),
        "aliases": (detail.get("extra") or {}).get("aliases"),
        "operations": (detail.get("extra") or {}).get("operations"),
        "suggestions": [
            {
                "id": str(row.id),
                "type": row.suggestion_type,
                "event_ids": row.event_ids,
                "reason": row.reason,
                "scores": row.scores,
                "status": row.status,
            }
            for row in suggestions
        ],
    }


@router.get("/shadow/today-preview", response_model=TodayHighlightsResponse)
async def preview_event_v1_today(
    digest_date: Optional[str] = Query(None, alias="date"),
    limit: int = Query(8, ge=3, le=8),
    db: AsyncSession = Depends(get_async_db),
):
    from app.domains.events.shadow import list_v1_today_cards

    target_date = datetime.strptime(digest_date, "%Y-%m-%d").date() if digest_date else today_in_user_timezone()
    items = await list_v1_today_cards(db, target_date, limit=limit)
    return TodayHighlightsResponse(date=target_date.isoformat(), items=items)


@router.post("/operations/merge")
async def merge_event_command(body: EventMergeCreate, db: AsyncSession = Depends(get_async_db)):
    from app.domains.events.operations import merge_events

    try:
        operation = await db.run_sync(
            lambda session: merge_events(
                session,
                canonical_event_id=body.canonical_event_id.strip(),
                source_event_ids=[value.strip() for value in body.source_event_ids],
                actor=body.actor.strip(),
                reason=body.reason.strip(),
            )
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return {"operation_id": str(operation.id), "canonical_event_id": body.canonical_event_id, "redirects": body.source_event_ids}


@router.post("/{event_id}/operations/split")
async def split_event_command(event_id: str, body: EventSplitCreate, db: AsyncSession = Depends(get_async_db)):
    from app.domains.events.operations import split_event

    try:
        operation = await db.run_sync(
            lambda session: split_event(
                session,
                event_id=event_id.strip(),
                groups=[[str(content_id).strip() for content_id in group] for group in body.groups],
                actor=body.actor.strip(),
                reason=body.reason.strip(),
            )
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return {"operation_id": str(operation.id), "source_event_id": event_id, "output_event_ids": operation.output_event_ids}


@router.post("/{event_id}/operations/lifecycle")
async def lifecycle_event_command(event_id: str, body: EventLifecycleCreate, db: AsyncSession = Depends(get_async_db)):
    from app.domains.events.operations import set_event_lifecycle

    try:
        operation = await db.run_sync(
            lambda session: set_event_lifecycle(
                session,
                event_id.strip(),
                action=body.action,
                actor=body.actor.strip(),
                reason=body.reason.strip(),
            )
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await db.commit()
    return {"operation_id": str(operation.id), "event_id": event_id, "action": body.action}


@router.post("/operations/{operation_id}/revert")
async def revert_event_command(operation_id: str, body: EventRevertCreate, db: AsyncSession = Depends(get_async_db)):
    from app.domains.events.operations import revert_operation

    try:
        operation = await db.run_sync(
            lambda session: revert_operation(
                session,
                operation_id.strip(),
                actor=body.actor.strip(),
                reason=body.reason.strip(),
            )
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return {"operation_id": str(operation.id), "reverted_operation_id": operation_id}


@router.post("/rebalance")
async def run_event_rebalance(body: EventRebalanceCreate, db: AsyncSession = Depends(get_async_db)):
    from app.domains.events.rebalance import run_rebalance

    result = await db.run_sync(
        lambda session: run_rebalance(
            session,
            run_kind=body.run_kind,
            max_events=body.max_events,
            max_pairs=body.max_pairs,
            max_runtime_seconds=body.max_runtime_seconds,
            checkpoint_size=body.checkpoint_size,
            resume_cursor=body.resume_cursor,
        )
    )
    await db.commit()
    return result


@router.get("/rebalance/runs")
async def list_event_rebalance_runs(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_async_db),
):
    rows = list(
        (
            await db.execute(
                select(EventRebalanceRun).order_by(EventRebalanceRun.created_at.desc()).limit(limit)
            )
        ).scalars().all()
    )
    return [
        {
            "id": str(row.id),
            "run_kind": row.run_kind,
            "status": row.status,
            "cursor": row.cursor,
            "scanned_event_count": row.scanned_event_count,
            "candidate_pair_count": row.candidate_pair_count,
            "filtered_closed_count": row.filtered_closed_count,
            "checkpoint_count": row.checkpoint_count,
            "wake_reasons": row.wake_reasons,
            "budgets": row.budgets,
            "summary": row.summary,
            "created_at": to_iso_z(row.created_at),
        }
        for row in rows
    ]


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
    limit: int = Query(50, ge=1, le=50),
    db: AsyncSession = Depends(get_async_db),
):
    """Return qualifying event cards from the rolling 48-hour highlights window.

    This endpoint reads persisted Events, not hourly Digest payloads. Empty
    ``items`` means no event currently meets the corroboration and heat gates.
    """

    target_date = datetime.strptime(digest_date, "%Y-%m-%d").date() if digest_date else today_in_user_timezone()
    items = await list_today_highlights(db, target_date, limit=limit)
    return TodayHighlightsResponse(date=target_date.isoformat(), items=items)


@router.get("/quality-feedback/queue", response_model=list[QualityFeedbackQueueItem])
async def list_quality_feedback_queue(
    status: str = Query("observation", pattern="^(observation|adjudicated|all)$"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_async_db),
):
    """List explicit quality observations; reading behavior is never included."""

    statement = (
        select(ScoreFeedback, QualityAdjudication)
        .outerjoin(QualityAdjudication, QualityAdjudication.feedback_id == ScoreFeedback.id)
        .where(ScoreFeedback.event_type.in_(sorted(_VALID_EVENT_FEEDBACK)))
    )
    if status == "observation":
        statement = statement.where(QualityAdjudication.id.is_(None))
    elif status == "adjudicated":
        statement = statement.where(QualityAdjudication.id.is_not(None))
    statement = statement.order_by(ScoreFeedback.created_at.asc()).limit(limit)
    rows = (await db.execute(statement)).all()
    items = []
    for feedback, adjudication in rows:
        row_status = "adjudicated" if adjudication else "observation"
        event_value = feedback.event_value if isinstance(feedback.event_value, dict) else {}
        items.append(
            QualityFeedbackQueueItem(
                feedback_id=str(feedback.id),
                event_id=event_value.get("event_id"),
                content_id=str(feedback.content_id),
                issue_type=str(feedback.event_type),
                note=feedback.note,
                status=row_status,
                verdict=adjudication.verdict if adjudication else None,
                gold_candidate=bool(adjudication and adjudication.gold_candidate),
                hard_negative=bool(adjudication and adjudication.hard_negative),
                observed_at=to_iso_z(feedback.created_at),
                adjudicated_at=to_iso_z(adjudication.created_at) if adjudication else None,
            )
        )
    return items


@router.post("/quality-feedback/{feedback_id}/adjudicate", response_model=QualityAdjudicationItem)
async def adjudicate_event_feedback(
    feedback_id: str,
    body: QualityAdjudicationCreate,
    db: AsyncSession = Depends(get_async_db),
):
    try:
        row = await adjudicate_quality_feedback(
            db,
            feedback_id.strip(),
            verdict=body.verdict.strip(),
            adjudicator=body.adjudicator,
            rationale=body.rationale,
            evidence=body.evidence,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(row)
    return QualityAdjudicationItem(
        id=str(row.id),
        feedback_id=str(row.feedback_id),
        issue_type=row.issue_type,
        status=row.status,
        verdict=row.verdict,
        adjudicator=row.adjudicator,
        rationale=row.rationale,
        gold_candidate=bool(row.gold_candidate),
        hard_negative=bool(row.hard_negative),
        created_at=to_iso_z(row.created_at),
    )


@router.get("/{event_id}", response_model=EventDetailResponse)
async def get_event_detail(
    event_id: str,
    full_reports: bool = Query(False),
    db: AsyncSession = Depends(get_async_db),
):
    from app.domains.events.operations import resolve_event

    resolved = await db.run_sync(lambda session: resolve_event(session, event_id.strip()))
    if resolved and resolved.get("kind") == "redirect":
        target = str(resolved.get("event_id") or "")
        raise HTTPException(
            status_code=308,
            detail={"kind": "redirect", "event_id": target},
            headers={"Location": f"/api/events/{target}"},
        )
    if resolved and resolved.get("kind") == "split":
        raise HTTPException(status_code=409, detail=resolved)
    detail = await build_event_detail(db, event_id.strip(), full_reports=full_reports)
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
    detail = None
    if body.content_id:
        content = (
            await db.execute(
                select(Content).options(selectinload(Content.source)).where(Content.id == str(body.content_id))
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
    if features.inline_annotations_enabled():
        if detail is None:
            detail = await build_event_detail(db, event_id.strip())
        timeline = (detail or {}).get("timeline") or []
        try:
            await record_annotation_label(
                db,
                task_type="event_correctness",
                target_type="event",
                target_id=event_id.strip(),
                label_payload={
                    "value": "incorrect" if feedback_type == "event_wrong_merge" else "partial"
                },
                note=body.note,
                context_snapshot={
                    "title": (detail or {}).get("title"),
                    "summary": (detail or {}).get("current_conclusion"),
                    "source_names": (detail or {}).get("source_names") or [],
                    "member_ids": [
                        item.get("content_id")
                        for item in timeline
                        if isinstance(item, dict) and item.get("content_id")
                    ],
                },
                reason="product-action",
            )
        except AnnotationTaskImmutableError:
            pass
    await db.commit()
    await db.refresh(row)
    from app.platform.observability.metrics import event_metrics

    event_metrics.increment("pim_event_feedback_total", labels={"type": feedback_type})
    return EventFeedbackItem(type=row.event_type or feedback_type, note=row.note, created_at=row.created_at.isoformat())
