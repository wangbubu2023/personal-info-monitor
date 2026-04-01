"""Pydantic schemas for Category model."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CategoryBase(BaseModel):
    """Base schema for Category."""
    
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    color: str = Field(default="#1890ff", pattern="^#[0-9A-Fa-f]{6}$")
    icon: Optional[str] = None
    parent_id: Optional[UUID] = None
    sort_order: int = Field(default=0, ge=0)


class CategoryCreate(CategoryBase):
    """Schema for creating a new Category."""
    pass


class CategoryUpdate(BaseModel):
    """Schema for updating a Category."""
    
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    color: Optional[str] = Field(None, pattern="^#[0-9A-Fa-f]{6}$")
    icon: Optional[str] = None
    parent_id: Optional[UUID] = None
    sort_order: Optional[int] = Field(None, ge=0)


class CategoryResponse(CategoryBase):
    """Schema for Category response."""
    
    id: UUID
    created_at: datetime
    updated_at: datetime
    source_count: int = 0
    children: List["CategoryResponse"] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


# Update forward reference
CategoryResponse.model_rebuild()


class CategoryTree(BaseModel):
    """Schema for category tree response."""
    
    categories: List[CategoryResponse]
