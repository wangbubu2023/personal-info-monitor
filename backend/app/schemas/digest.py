"""Pydantic schemas for Digest."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DigestItem(BaseModel):
    """Schema for a single digest item."""
    
    id: UUID
    source_id: UUID
    source_name: str
    title: str
    translated_title: Optional[str] = None
    summary: Optional[str] = None
    translated_summary: Optional[str] = None
    body_preview: Optional[str] = Field(
        default=None,
        description="无有效摘要时由正文截取的列表预览（纯文本）",
    )
    url: str
    publish_time: Optional[datetime] = None
    fetched_at: Optional[datetime] = None
    read_status: bool = False
    favorited: bool = False
    keyword_matches: List[Dict[str, Any]] = []
    metadata_: Dict[str, Any] = Field(default_factory=dict, alias="metadata")


class DigestCategory(BaseModel):
    """Schema for a category in the digest."""
    
    count: int = 0
    items: List[DigestItem] = []


class DigestResponse(BaseModel):
    """Schema for daily digest response."""
    
    date: str
    total_items: int
    categories: Dict[str, DigestCategory]
    # {
    #     "websites": { "count": 10, "items": [...] },
    #     "rss": { "count": 3, "items": [...] },
    #     "x_accounts": { "count": 5, "items": [...] },
    #     "youtube": { "count": 3, "items": [...] },
    #     "podcasts": { "count": 2, "items": [...] }
    # }


class DigestParams(BaseModel):
    """Schema for digest query parameters."""
    
    date: Optional[str] = None  # YYYY-MM-DD format
    keyword_ids: Optional[List[UUID]] = None
    unread_only: bool = True
    source_types: Optional[List[str]] = None


class HourlyDigestSummary(BaseModel):
    """Schema for hourly digest list item."""
    
    hour: int
    title: Optional[str] = None
    content_count: int
    summary: Optional[str] = None
    generated_at: Optional[str] = None
    sources: Dict[str, int] = {
        "websites": 0,
        "x": 0,
        "youtube": 0,
        "podcasts": 0,
    }


class HourlyDigestEventItem(BaseModel):
    """Structured event card stored with an hourly digest."""

    event_key: Optional[str] = None
    event_id: Optional[str] = None
    section: Optional[str] = None
    content_id: UUID
    content_ids: List[UUID] = Field(default_factory=list)
    title: str
    article_title: Optional[str] = None
    summary: Optional[str] = None
    what_happened: Optional[str] = None
    why_matters: Optional[str] = None
    new_signal: Optional[str] = None
    missing_confirmation: Optional[str] = None
    source_name: str
    source_names: List[str] = Field(default_factory=list)
    source_keys: List[str] = Field(default_factory=list)
    source_url: Optional[str] = None
    url: str
    local_reader_path: Optional[str] = None
    publish_time: Optional[str] = None
    fetched_at: Optional[str] = None
    score: Optional[float] = None
    importance_score: Optional[float] = None
    incremental_score: Optional[float] = None
    confidence_score: Optional[float] = None
    lane: Optional[str] = None
    duplicate_group_id: Optional[str] = None
    corroboration_tier: Optional[str] = None
    independent_source_count: Optional[int] = None
    is_repeat_event: bool = False


class HourlyDigestDetail(BaseModel):
    """Schema for hourly digest detail with AI summary."""
    
    hour: int
    date: str
    title: Optional[str] = None
    summary: Optional[str] = None
    content_count: int = 0
    sources: List[str] = []
    event_items: List[HourlyDigestEventItem] = []
    items: List[DigestItem] = []
    generated_at: Optional[str] = None
