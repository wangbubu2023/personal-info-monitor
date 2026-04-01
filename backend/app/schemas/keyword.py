"""Pydantic schemas for Keyword model."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class KeywordBase(BaseModel):
    """Base schema for Keyword."""
    
    keyword: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    match_type: str = Field(default="contains", pattern="^(exact|contains|regex)$")
    case_sensitive: bool = False
    notify: bool = True
    notify_email: bool = False
    color: str = Field(default="#ff4d4f", pattern="^#[0-9A-Fa-f]{6}$")
    enabled: bool = True


class KeywordCreate(KeywordBase):
    """Schema for creating a new Keyword."""
    pass


class KeywordUpdate(BaseModel):
    """Schema for updating a Keyword."""
    
    keyword: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    match_type: Optional[str] = Field(None, pattern="^(exact|contains|regex)$")
    case_sensitive: Optional[bool] = None
    notify: Optional[bool] = None
    notify_email: Optional[bool] = None
    color: Optional[str] = Field(None, pattern="^#[0-9A-Fa-f]{6}$")
    enabled: Optional[bool] = None


class KeywordResponse(KeywordBase):
    """Schema for Keyword response."""
    
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class KeywordListResponse(BaseModel):
    """Schema for Keyword list response."""
    
    items: List[KeywordResponse]
    total: int
