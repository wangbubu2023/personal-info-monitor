"""Shared append-only annotation recording used by APIs and product actions."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import AnnotationLabel, AnnotationTask
from app.utils.datetime import utcnow_naive


class AnnotationTaskImmutableError(RuntimeError):
    """Raised when a product action would mutate an adjudicated task."""


def annotation_fingerprint(
    target_type: str,
    target_id: str,
    secondary_target_id: str | None = None,
) -> str:
    raw = "\x1f".join(
        (
            target_type.strip(),
            target_id.strip(),
            (secondary_target_id or "").strip(),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def record_annotation_label(
    db: AsyncSession,
    *,
    task_type: str,
    target_type: str,
    target_id: str,
    label_payload: dict[str, Any],
    secondary_target_id: str | None = None,
    schema_version: str = "v1",
    note: str | None = None,
    confidence: float | None = None,
    annotator: str = "local-user",
    context_snapshot: dict[str, Any] | None = None,
    prediction_snapshot: dict[str, Any] | None = None,
    independent: bool = False,
    reason: str = "inline-consumption",
) -> tuple[AnnotationLabel, AnnotationTask]:
    """Record a label without committing, so callers can share their transaction."""
    normalized_target_id = target_id.strip()
    normalized_secondary = (secondary_target_id or "").strip() or None
    fingerprint = annotation_fingerprint(target_type, normalized_target_id, normalized_secondary)
    statement = (
        select(AnnotationTask)
        .options(selectinload(AnnotationTask.labels))
        .where(
            AnnotationTask.task_type == task_type.strip(),
            AnnotationTask.target_fingerprint == fingerprint,
            AnnotationTask.schema_version == schema_version,
        )
    )
    task = (await db.execute(statement)).scalar_one_or_none()
    now = utcnow_naive()
    if task is None:
        task = AnnotationTask(
            task_type=task_type.strip(),
            target_type=target_type.strip(),
            target_id=normalized_target_id,
            secondary_target_id=normalized_secondary,
            target_fingerprint=fingerprint,
            schema_version=schema_version,
            status="labeled",
            reason=reason,
            context_snapshot=context_snapshot or {},
            prediction_snapshot=prediction_snapshot or {},
            created_at=now,
            updated_at=now,
        )
        db.add(task)
        await db.flush()
        previous = None
    else:
        if task.status == "adjudicated":
            raise AnnotationTaskImmutableError("Adjudicated tasks are immutable")
        previous = task.labels[-1] if task.labels else None
        if (
            previous is not None
            and previous.label_payload == label_payload
            and (previous.note or "") == ((note or "").strip())
            and not independent
        ):
            task.status = "labeled"
            task.updated_at = now
            return previous, task
        if context_snapshot and not task.context_snapshot:
            task.context_snapshot = context_snapshot
        if prediction_snapshot and not task.prediction_snapshot:
            task.prediction_snapshot = prediction_snapshot
        # A legacy product action may have created this task before a user uses
        # the dedicated inline control.  Let the latter become the task's
        # canonical purpose so consumers can distinguish stale action records.
        if task.reason == "product-action" and reason != "product-action":
            task.reason = reason
        task.updated_at = now

    label = AnnotationLabel(
        task_id=task.id,
        annotator=annotator.strip(),
        label_payload=label_payload,
        note=(note or "").strip() or None,
        confidence=confidence,
        supersedes_id=None if independent or previous is None else previous.id,
        created_at=now,
    )
    db.add(label)
    if independent and previous is not None and previous.label_payload != label_payload:
        task.status = "needs_adjudication"
    else:
        task.status = "labeled"
    await db.flush()
    return label, task


async def retract_annotation_task(
    db: AsyncSession,
    *,
    task_type: str,
    target_type: str,
    target_id: str,
    secondary_target_id: str | None = None,
    schema_version: str = "v1",
) -> None:
    """Mark an inferred label inactive while preserving its audit history."""
    fingerprint = annotation_fingerprint(target_type, target_id, secondary_target_id)
    task = (
        await db.execute(
            select(AnnotationTask).where(
                AnnotationTask.task_type == task_type.strip(),
                AnnotationTask.target_fingerprint == fingerprint,
                AnnotationTask.schema_version == schema_version,
            )
        )
    ).scalar_one_or_none()
    if task is None or task.status == "adjudicated":
        return
    task.status = "retracted"
    task.updated_at = utcnow_naive()
