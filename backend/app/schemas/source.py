"""Pydantic schemas for Source model."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SourceBase(BaseModel):
    """Base schema for Source."""
    
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., pattern="^(website|rss|x|youtube|podcast)$")
    url: str = Field(..., min_length=1)
    extra_urls: List[str] = Field(default_factory=list)
    category_id: Optional[UUID] = None
    fetch_interval: int = Field(default=60, ge=15, le=1440)  # 15 min to 24 hours
    enabled: bool = True
    priority: int = Field(default=0, ge=0, le=100)
    auth_required: bool = False
    auth_config_id: Optional[UUID] = None
    metadata_: Optional[Dict[str, Any]] = Field(default_factory=dict, alias="metadata")


class SourceCreate(SourceBase):
    """Schema for creating a new Source."""
    pass


class SourceUpdate(BaseModel):
    """Schema for updating a Source."""
    
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    type: Optional[str] = Field(None, pattern="^(website|rss|x|youtube|podcast)$")
    url: Optional[str] = Field(None, min_length=1)
    extra_urls: Optional[List[str]] = None
    category_id: Optional[UUID] = None
    fetch_interval: Optional[int] = Field(None, ge=15, le=1440)
    enabled: Optional[bool] = None
    priority: Optional[int] = Field(None, ge=0, le=100)
    auth_required: Optional[bool] = None
    auth_config_id: Optional[UUID] = None
    metadata_: Optional[Dict[str, Any]] = Field(None, alias="metadata")


class SourceResponse(SourceBase):
    """Schema for Source response."""
    
    id: UUID
    last_fetched_at: Optional[datetime] = None
    last_content_id: Optional[str] = None
    last_error: Optional[str] = None
    error_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SourceListResponse(BaseModel):
    """Schema for paginated Source list response."""
    
    items: List[SourceResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class SourceBulkImport(BaseModel):
    """Schema for bulk importing sources."""
    
    sources: List[SourceCreate]


class SourceExport(BaseModel):
    """Schema for exporting sources."""
    
    sources: List[SourceResponse]
    exported_at: datetime
