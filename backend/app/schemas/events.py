"""Schemas for Event v0 APIs."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class TodayHighlightEvent(BaseModel):
    event_id: str
    event_key: str
    section: Optional[str] = None
    title: str
    summary: Optional[str] = None
    why_matters: Optional[str] = None
    what_changed: Optional[str] = None
    independent_source_count: int = 0
    source_names: list[str] = Field(default_factory=list)
    updated_at: Optional[str] = None
    importance_score: Optional[float] = None
    confidence_score: Optional[float] = None
    primary_content_id: Optional[str] = None
    latest_version: int = 0
    user_seen_version: int = 0
    has_updates: bool = False


class TodayHighlightsResponse(BaseModel):
    date: str
    items: list[TodayHighlightEvent] = Field(default_factory=list)


class EventTimelineItem(BaseModel):
    content_id: str
    title: str
    summary: Optional[str] = None
    source_name: str
    url: str
    publish_time: Optional[str] = None
    fetched_at: Optional[str] = None
    role: str = "supporting"


class EventSnapshotItem(BaseModel):
    version: int
    title: str
    summary: Optional[str] = None
    what_changed: Optional[str] = None
    why_matters: Optional[str] = None
    created_at: Optional[str] = None
    is_seen: bool = False


class EventFeedbackCreate(BaseModel):
    type: str
    note: Optional[str] = None
    content_id: Optional[str] = None


class EventFeedbackItem(BaseModel):
    type: str
    note: Optional[str] = None
    created_at: Optional[str] = None


class EventEvidenceGroup(BaseModel):
    key: str
    title: str
    content_ids: list[str] = Field(default_factory=list)


class EventDetailResponse(BaseModel):
    event_id: str
    event_key: str
    title: str
    current_conclusion: str
    why_matters: Optional[str] = None
    source_names: list[str] = Field(default_factory=list)
    independent_source_count: int = 0
    updated_at: Optional[str] = None
    latest_version: int = 0
    user_seen_version: int = 0
    has_updates: bool = False
    saved: bool = False
    read_later: bool = False
    hidden: bool = False
    timeline: list[EventTimelineItem] = Field(default_factory=list)
    snapshots: list[EventSnapshotItem] = Field(default_factory=list)
    primary_reports: list[EventTimelineItem] = Field(default_factory=list)
    independent_verification: list[EventEvidenceGroup] = Field(default_factory=list)
    related_discussions: list[EventEvidenceGroup] = Field(default_factory=list)
    feedback: list[EventFeedbackItem] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
