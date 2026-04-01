"""Pydantic schemas for Content model."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContentBase(BaseModel):
    """Base schema for Content."""
    
    title: str
    translated_title: Optional[str] = None
    summary: Optional[str] = None
    translated_summary: Optional[str] = None
    original_url: str
    full_content: Optional[str] = None
    content_type: str
    publish_time: Optional[datetime] = None


class ContentResponse(ContentBase):
    """Schema for Content response."""
    
    id: UUID
    source_id: UUID
    external_id: Optional[str] = None
    read_status: bool = False
    favorited: bool = False
    archived: bool = False
    keyword_matches: List[Dict[str, Any]] = Field(default_factory=list)
    metadata_: Dict[str, Any] = Field(default_factory=dict, alias="metadata")
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime
    
    # Nested source info
    source_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ContentListResponse(BaseModel):
    """Schema for paginated Content list response."""
    
    items: List[ContentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class ContentUpdate(BaseModel):
    """Schema for updating Content."""
    
    read_status: Optional[bool] = None
    favorited: Optional[bool] = None
    archived: Optional[bool] = None


class ContentSearchParams(BaseModel):
    """Schema for content search parameters."""
    
    q: Optional[str] = None
    source_type: Optional[str] = None
    source_id: Optional[UUID] = None
    category_id: Optional[UUID] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    read_status: Optional[bool] = None
    favorited: Optional[bool] = None
    keyword_id: Optional[UUID] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)
