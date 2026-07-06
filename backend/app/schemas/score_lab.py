"""Pydantic schemas for score lab API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ScoreLabContentSummary(BaseModel):
    id: UUID
    title: str
    source_name: Optional[str] = None
    content_type: str
    original_url: str
    publish_time: Optional[datetime] = None
    fetched_at: Optional[datetime] = None
    article_score: Optional[float] = None
    selection_status: Optional[str] = None
    lane: Optional[str] = None
    fetch_acceptance: Optional[str] = None


class ScoreLabContentListResponse(BaseModel):
    items: list[ScoreLabContentSummary]
    total: int
    page: int
    page_size: int


class ScoreFeedbackCreate(BaseModel):
    content_id: UUID
    direction: Literal["too_high", "too_low", "ok"]
    expected_status: Optional[Literal["selected", "candidate", "rejected"]] = None
    note: Optional[str] = Field(default=None, max_length=2000)


class ScoreFeedbackItem(BaseModel):
    id: UUID
    content_id: UUID
    direction: str
    expected_status: Optional[str] = None
    note: Optional[str] = None
    event_type: Optional[str] = None
    event_value: Any = None
    snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    content_title: Optional[str] = None


class ScoreFeedbackListResponse(BaseModel):
    items: list[ScoreFeedbackItem]
    total: int


class ScoreExplainResponse(BaseModel):
    explain: dict[str, Any]
