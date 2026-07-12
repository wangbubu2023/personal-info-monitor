"""Schemas for personal monitor state APIs."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class PersonalItemStateResponse(BaseModel):
    target_type: str
    target_id: str
    last_seen_version: int = 0
    saved: bool = False
    read_later: bool = False
    hidden: bool = False
    read_at: Optional[str] = None
    updated_at: Optional[str] = None


class EventReadStateResponse(BaseModel):
    event_id: str
    latest_version: int
    user_seen_version: int
    has_updates: bool
    state: PersonalItemStateResponse


class EventStateUpdate(BaseModel):
    saved: Optional[bool] = None
    read_later: Optional[bool] = None
    hidden: Optional[bool] = None


class ReportStateUpdate(BaseModel):
    saved: Optional[bool] = None
    read_later: Optional[bool] = None
    hidden: Optional[bool] = None
    completed: Optional[bool] = None


class ObservationAggregateResponse(BaseModel):
    id: int
    scope_type: str
    scope_key: str
    positive_evidence_count: int = 0
    negative_evidence_count: int = 0
    confidence: float = 0.0
    suggestion_status: str = "none"
    suggested_rule: Optional[str] = None
    evidence_summary: Optional[str] = None
    recent_activity_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UserRuleCreate(BaseModel):
    scope_type: str
    scope_key: str
    rule: str
    evidence_summary: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UserRuleUpdate(BaseModel):
    rule: Optional[str] = None
    status: Optional[str] = None
    evidence_summary: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class UserRuleResponse(BaseModel):
    id: str
    scope_type: str
    scope_key: str
    rule: str
    status: str
    created_by: str
    evidence_summary: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
