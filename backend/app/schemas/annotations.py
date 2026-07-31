"""API contracts for inline annotation and exceptional adjudication."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AnnotationTargetType = Literal["content", "event", "atom", "event_pair", "atom_relation"]


class AnnotationLabelCreate(BaseModel):
    task_type: str = Field(min_length=1, max_length=48)
    target_type: AnnotationTargetType
    target_id: str = Field(min_length=1, max_length=128)
    secondary_target_id: str | None = Field(default=None, max_length=128)
    schema_version: str = Field(default="v1", min_length=1, max_length=24)
    label_payload: dict[str, Any]
    note: str | None = Field(default=None, max_length=4000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    annotator: str = Field(default="local-user", min_length=1, max_length=128)
    context_snapshot: dict[str, Any] = Field(default_factory=dict)
    prediction_snapshot: dict[str, Any] = Field(default_factory=dict)
    independent: bool = False


class AnnotationLabelItem(BaseModel):
    id: str
    task_id: str
    task_type: str
    target_type: str
    target_id: str
    label_payload: dict[str, Any]
    note: str | None = None
    confidence: float | None = None
    annotator: str
    supersedes_id: str | None = None
    task_status: str
    created_at: str | None = None


class AnnotationTaskItem(BaseModel):
    id: str
    task_type: str
    target_type: str
    target_id: str
    secondary_target_id: str | None = None
    schema_version: str
    status: str
    priority: float
    reason: str | None = None
    context_snapshot: dict[str, Any] = Field(default_factory=dict)
    prediction_snapshot: dict[str, Any] = Field(default_factory=dict)
    source_dataset: str | None = None
    review_bucket: str | None = None
    labels: list[AnnotationLabelItem] = Field(default_factory=list)
    latest_label: AnnotationLabelItem | None = None
    label_count: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class TargetAnnotationsResponse(BaseModel):
    target_type: str
    target_id: str
    items: list[AnnotationTaskItem] = Field(default_factory=list)


class AnnotationReviewQueueResponse(BaseModel):
    items: list[AnnotationTaskItem] = Field(default_factory=list)
    total: int
    bucket_counts: dict[str, int] = Field(default_factory=dict)


class AnnotationAdjudicationCreate(BaseModel):
    final_payload: dict[str, Any]
    rationale: str = Field(min_length=1, max_length=4000)
    adjudicator: str = Field(default="local-user", min_length=1, max_length=128)
    gold_candidate: bool = True


class AnnotationAdjudicationItem(BaseModel):
    id: str
    task_id: str
    final_payload: dict[str, Any]
    rationale: str
    adjudicator: str
    gold_candidate: bool
    created_at: str | None = None


class AnnotationStatsResponse(BaseModel):
    pending: int = 0
    needs_adjudication: int = 0
    labeled: int = 0
    adjudicated: int = 0
    retracted: int = 0
    total: int = 0
    by_task_type: dict[str, int] = Field(default_factory=dict)
    central_review: int = 0
    taxonomy_migration: int = 0
    deferred: int = 0
