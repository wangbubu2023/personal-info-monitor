"""Development-only API for low-friction inline human annotation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import features
from app.domains.score.score_vocab import VALID_LANES
from app.domains.eval.annotation_recording import (
    AnnotationTaskImmutableError,
    record_annotation_label,
)
from app.models import AnnotationAdjudication, AnnotationLabel, AnnotationTask
from app.platform.persistence.database import get_async_db
from app.schemas.annotations import (
    AnnotationAdjudicationCreate,
    AnnotationAdjudicationItem,
    AnnotationLabelCreate,
    AnnotationLabelItem,
    AnnotationReviewQueueResponse,
    AnnotationStatsResponse,
    AnnotationTaskItem,
    TargetAnnotationsResponse,
)
from app.utils.datetime import to_iso_z, utcnow_naive

router = APIRouter()

_TASK_TARGETS: dict[str, str] = {
    "content_value": "content",
    "content_relevance": "content",
    "content_quality": "content",
    "content_format_quality": "content",
    "content_fact_density": "content",
    "content_lane": "content",
    "content_tags": "content",
    "event_correctness": "event",
    "event_membership": "event",
    "event_pair_relation": "event_pair",
    "atom_validity": "atom",
    "atom_relation": "atom_relation",
}

_TASK_VALUES: dict[str, frozenset[str]] = {
    "content_value": frozenset({"must_see", "ok", "noise"}),
    "content_relevance": frozenset({"high", "medium", "low", "unclear"}),
    "content_quality": frozenset({"high", "medium", "low", "unclear"}),
    "content_format_quality": frozenset({"high", "medium", "low"}),
    "content_fact_density": frozenset({"dense", "moderate", "sparse", "unclear"}),
    "content_lane": frozenset(VALID_LANES),
    "event_correctness": frozenset({"correct", "partial", "incorrect", "unclear"}),
    "event_membership": frozenset({"belongs", "not_belongs", "unclear"}),
    "event_pair_relation": frozenset(
        {"same_event", "event_update", "commentary", "duplicate", "unrelated", "unclear"}
    ),
    "atom_validity": frozenset({"valid", "partial", "invalid", "unclear"}),
    "atom_relation": frozenset({"supports", "contradicts", "supersedes", "duplicate", "unrelated", "unclear"}),
}


def require_development_annotations() -> None:
    if not features.inline_annotations_enabled():
        raise HTTPException(status_code=404, detail="Inline annotations are available only in development profile")


def _validate_label(task_type: str, target_type: str, payload: dict[str, Any]) -> None:
    expected_target = _TASK_TARGETS.get(task_type)
    if expected_target is None:
        raise HTTPException(status_code=422, detail=f"Unsupported annotation task type: {task_type}")
    if expected_target != target_type:
        raise HTTPException(
            status_code=422,
            detail=f"{task_type} requires target_type={expected_target}",
        )
    if task_type == "content_tags":
        values = payload.get("values")
        valid = (
            isinstance(values, list)
            and 1 <= len(values) <= 4
            and len(values) == len(set(values))
            and all(isinstance(value, str) and value in VALID_LANES for value in values)
        )
        if not valid:
            raise HTTPException(
                status_code=422,
                detail="content_tags requires 1-4 unique canonical tag values",
            )
        return
    value = payload.get("value")
    if value not in _TASK_VALUES[task_type]:
        allowed = ", ".join(sorted(_TASK_VALUES[task_type]))
        raise HTTPException(status_code=422, detail=f"Invalid label value; expected one of: {allowed}")


def _label_item(label: AnnotationLabel, task: AnnotationTask) -> AnnotationLabelItem:
    return AnnotationLabelItem(
        id=str(label.id),
        task_id=str(task.id),
        task_type=task.task_type,
        target_type=task.target_type,
        target_id=task.target_id,
        label_payload=label.label_payload if isinstance(label.label_payload, dict) else {},
        note=label.note,
        confidence=label.confidence,
        annotator=label.annotator,
        supersedes_id=str(label.supersedes_id) if label.supersedes_id else None,
        task_status=task.status,
        created_at=to_iso_z(label.created_at),
    )


def _task_item(task: AnnotationTask) -> AnnotationTaskItem:
    latest = task.labels[-1] if task.labels else None
    return AnnotationTaskItem(
        id=str(task.id),
        task_type=task.task_type,
        target_type=task.target_type,
        target_id=task.target_id,
        secondary_target_id=task.secondary_target_id,
        schema_version=task.schema_version,
        status=task.status,
        priority=float(task.priority or 0),
        reason=task.reason,
        context_snapshot=task.context_snapshot if isinstance(task.context_snapshot, dict) else {},
        prediction_snapshot=task.prediction_snapshot if isinstance(task.prediction_snapshot, dict) else {},
        source_dataset=task.source_dataset,
        latest_label=_label_item(latest, task) if latest else None,
        label_count=len(task.labels),
        created_at=to_iso_z(task.created_at),
        updated_at=to_iso_z(task.updated_at),
    )


@router.post(
    "/labels",
    response_model=AnnotationLabelItem,
    dependencies=[Depends(require_development_annotations)],
)
async def submit_annotation_label(
    body: AnnotationLabelCreate,
    db: AsyncSession = Depends(get_async_db),
) -> AnnotationLabelItem:
    task_type = body.task_type.strip()
    target_id = body.target_id.strip()
    _validate_label(task_type, body.target_type, body.label_payload)
    try:
        label, task = await record_annotation_label(
            db,
            task_type=task_type,
            target_type=body.target_type,
            target_id=target_id,
            secondary_target_id=body.secondary_target_id,
            schema_version=body.schema_version,
            label_payload=body.label_payload,
            note=body.note,
            confidence=body.confidence,
            annotator=body.annotator,
            context_snapshot=body.context_snapshot,
            prediction_snapshot=body.prediction_snapshot,
            independent=body.independent,
        )
    except AnnotationTaskImmutableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(label)
    return _label_item(label, task)


@router.get(
    "/targets/{target_type}/{target_id}",
    response_model=TargetAnnotationsResponse,
    dependencies=[Depends(require_development_annotations)],
)
async def get_target_annotations(
    target_type: str,
    target_id: str,
    db: AsyncSession = Depends(get_async_db),
) -> TargetAnnotationsResponse:
    statement = (
        select(AnnotationTask)
        .options(selectinload(AnnotationTask.labels))
        .where(
            AnnotationTask.target_type == target_type.strip(),
            AnnotationTask.target_id == target_id.strip(),
        )
        .order_by(AnnotationTask.created_at.asc())
    )
    tasks = (await db.execute(statement)).scalars().all()
    return TargetAnnotationsResponse(
        target_type=target_type,
        target_id=target_id,
        items=[_task_item(task) for task in tasks],
    )


@router.get(
    "/review-queue",
    response_model=AnnotationReviewQueueResponse,
    dependencies=[Depends(require_development_annotations)],
)
async def get_annotation_review_queue(
    status: str = Query("actionable", pattern="^(actionable|pending|needs_adjudication|all)$"),
    task_type: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_async_db),
) -> AnnotationReviewQueueResponse:
    filters = []
    if status == "actionable":
        filters.append(AnnotationTask.status.in_(("pending", "needs_adjudication")))
    elif status != "all":
        filters.append(AnnotationTask.status == status)
    if task_type:
        filters.append(AnnotationTask.task_type == task_type.strip())

    count_statement = select(func.count(AnnotationTask.id))
    list_statement = select(AnnotationTask).options(selectinload(AnnotationTask.labels))
    if filters:
        count_statement = count_statement.where(*filters)
        list_statement = list_statement.where(*filters)
    total = int((await db.execute(count_statement)).scalar() or 0)
    tasks = (
        (
            await db.execute(
                list_statement
                .order_by(AnnotationTask.priority.desc(), AnnotationTask.created_at.asc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return AnnotationReviewQueueResponse(items=[_task_item(task) for task in tasks], total=total)


@router.post(
    "/tasks/{task_id}/adjudicate",
    response_model=AnnotationAdjudicationItem,
    dependencies=[Depends(require_development_annotations)],
)
async def adjudicate_annotation_task(
    task_id: str,
    body: AnnotationAdjudicationCreate,
    db: AsyncSession = Depends(get_async_db),
) -> AnnotationAdjudicationItem:
    task = await db.get(AnnotationTask, task_id.strip())
    if task is None:
        raise HTTPException(status_code=404, detail="Annotation task not found")
    if task.status == "adjudicated":
        raise HTTPException(status_code=409, detail="Annotation task already adjudicated")
    _validate_label(task.task_type, task.target_type, body.final_payload)
    row = AnnotationAdjudication(
        task_id=task.id,
        final_payload=body.final_payload,
        adjudicator=body.adjudicator.strip(),
        rationale=body.rationale.strip(),
        gold_candidate=body.gold_candidate,
    )
    db.add(row)
    task.status = "adjudicated"
    task.updated_at = utcnow_naive()
    await db.commit()
    await db.refresh(row)
    return AnnotationAdjudicationItem(
        id=str(row.id),
        task_id=str(row.task_id),
        final_payload=row.final_payload,
        rationale=row.rationale,
        adjudicator=row.adjudicator,
        gold_candidate=bool(row.gold_candidate),
        created_at=to_iso_z(row.created_at),
    )


@router.get(
    "/stats",
    response_model=AnnotationStatsResponse,
    dependencies=[Depends(require_development_annotations)],
)
async def get_annotation_stats(db: AsyncSession = Depends(get_async_db)) -> AnnotationStatsResponse:
    status_rows = (
        await db.execute(select(AnnotationTask.status, func.count(AnnotationTask.id)).group_by(AnnotationTask.status))
    ).all()
    type_rows = (
        await db.execute(
            select(AnnotationTask.task_type, func.count(AnnotationTask.id)).group_by(AnnotationTask.task_type)
        )
    ).all()
    statuses = {str(status): int(count) for status, count in status_rows}
    total = sum(statuses.values())
    return AnnotationStatsResponse(
        pending=statuses.get("pending", 0),
        needs_adjudication=statuses.get("needs_adjudication", 0),
        labeled=statuses.get("labeled", 0),
        adjudicated=statuses.get("adjudicated", 0),
        retracted=statuses.get("retracted", 0),
        total=total,
        by_task_type={str(task_type): int(count) for task_type, count in type_rows},
    )
