"""Pydantic schemas for Keyword model."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class KeywordBase(BaseModel):
    """Base schema for Keyword."""
    
    keyword: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    match_type: str = Field(default="contains", pattern="^(exact|contains|regex)$")
    match_scope: str = Field(default="title_content", pattern="^(title|content|title_content)$")
    case_sensitive: bool = False
    manual_equivalent_terms: List[str] = Field(default_factory=list)
    include_auto_equivalent_terms: bool = True

    @field_validator("manual_equivalent_terms", mode="before")
    @classmethod
    def manual_equivalent_terms_coerce(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(x) for x in value]
        return []

    @field_validator("include_auto_equivalent_terms", mode="before")
    @classmethod
    def include_auto_coerce(cls, value: object) -> bool:
        if value is None:
            return True
        return bool(value)
    notify: bool = False
    notify_email: bool = False
    color: str = Field(default="#ff4d4f", pattern="^#[0-9A-Fa-f]{6}$")
    enabled: bool = True


class KeywordCreate(KeywordBase):
    """Schema for creating a new Keyword."""
    pass


class KeywordBatchCreate(BaseModel):
    """Schema for batch-creating keywords with shared settings."""

    keywords: List[str] = Field(..., min_length=1)
    description: Optional[str] = None
    match_type: str = Field(default="contains", pattern="^(exact|contains|regex)$")
    match_scope: str = Field(default="title_content", pattern="^(title|content|title_content)$")
    case_sensitive: bool = False
    manual_equivalent_terms: List[str] = Field(default_factory=list)
    include_auto_equivalent_terms: bool = True
    notify: bool = False
    notify_email: bool = False
    color: str = Field(default="#ff4d4f", pattern="^#[0-9A-Fa-f]{6}$")
    enabled: bool = True


class KeywordBatchUpdate(BaseModel):
    """Schema for batch-updating keywords."""

    keyword_ids: List[UUID] = Field(..., min_length=1)
    color: Optional[str] = Field(None, pattern="^#[0-9A-Fa-f]{6}$")
    match_scope: Optional[str] = Field(None, pattern="^(title|content|title_content)$")
    match_type: Optional[str] = Field(None, pattern="^(exact|contains|regex)$")
    enabled: Optional[bool] = None


class KeywordUpdate(BaseModel):
    """Schema for updating a Keyword."""

    keyword: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    match_type: Optional[str] = Field(None, pattern="^(exact|contains|regex)$")
    match_scope: Optional[str] = Field(None, pattern="^(title|content|title_content)$")
    case_sensitive: Optional[bool] = None
    manual_equivalent_terms: Optional[List[str]] = None
    include_auto_equivalent_terms: Optional[bool] = None
    notify: Optional[bool] = None
    notify_email: Optional[bool] = None
    color: Optional[str] = Field(None, pattern="^#[0-9A-Fa-f]{6}$")
    enabled: Optional[bool] = None

    @field_validator("manual_equivalent_terms", mode="before")
    @classmethod
    def manual_equivalent_terms_coerce(cls, value: object) -> list[str] | None:
        """与 KeywordBase 一致；若误传为单个字符串则按一行处理。"""
        if value is None:
            return None
        if isinstance(value, str):
            v = value.strip()
            return [] if not v else [v]
        if isinstance(value, list):
            return [str(x) for x in value]
        return []

    @field_validator("include_auto_equivalent_terms", mode="before")
    @classmethod
    def include_auto_coerce_update(cls, value: object) -> bool | None:
        if value is None:
            return None
        return bool(value)


class KeywordResponse(KeywordBase):
    """Schema for Keyword response."""
    
    id: UUID
    equivalent_terms: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("equivalent_terms", mode="before")
    @classmethod
    def equivalent_terms_coerce(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(x) for x in value]
        return []


class KeywordListResponse(BaseModel):
    """Schema for Keyword list response."""
    
    items: List[KeywordResponse]
    total: int


class KeywordBatchCreateResponse(BaseModel):
    """Schema for batch keyword create response."""

    items: List[KeywordResponse]
    total: int
    skipped_keywords: List[str] = Field(default_factory=list)


class KeywordBatchUpdateResponse(BaseModel):
    """Schema for batch keyword update response."""

    items: List[KeywordResponse]
    total: int
