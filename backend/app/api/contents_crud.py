"""CRUD routes for content management."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.content_shared import _serialize_content
from app.database import get_async_db
from app.models import Content, Source
from app.schemas.content import ContentListResponse, ContentResponse, ContentUpdate

router = APIRouter()
MAX_CONTENTS_PAGE_SIZE = 200


@router.get("", response_model=ContentListResponse)
async def list_contents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_CONTENTS_PAGE_SIZE),
    source_id: Optional[UUID] = None,
    source_type: Optional[str] = None,
    category_id: Optional[UUID] = None,
    read_status: Optional[bool] = None,
    favorited: Optional[bool] = None,
    archived: Optional[bool] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db),
):
    """List all content with pagination and filters."""
    query = select(Content).options(selectinload(Content.source))
    count_query = select(func.count(Content.id))

    if source_id:
        query = query.filter(Content.source_id == source_id)
        count_query = count_query.filter(Content.source_id == source_id)
    if source_type:
        query = query.filter(Content.content_type == source_type)
        count_query = count_query.filter(Content.content_type == source_type)
    if category_id:
        query = query.join(Source).filter(Source.category_id == category_id)
        count_query = count_query.join(Source).filter(Source.category_id == category_id)
    if read_status is not None:
        query = query.filter(Content.read_status == read_status)
        count_query = count_query.filter(Content.read_status == read_status)
    if favorited is not None:
        query = query.filter(Content.favorited == favorited)
        count_query = count_query.filter(Content.favorited == favorited)
    if archived is not None:
        query = query.filter(Content.archived == archived)
        count_query = count_query.filter(Content.archived == archived)
    if date_from:
        query = query.filter(Content.publish_time >= date_from)
        count_query = count_query.filter(Content.publish_time >= date_from)
    if date_to:
        query = query.filter(Content.publish_time <= date_to)
        count_query = count_query.filter(Content.publish_time <= date_to)
    if search:
        search_filter = or_(
            Content.title.ilike(f"%{search}%"),
            Content.summary.ilike(f"%{search}%"),
            Content.full_content.ilike(f"%{search}%"),
        )
        query = query.filter(search_filter)
        count_query = count_query.filter(search_filter)

    total = await db.scalar(count_query) or 0
    offset = (page - 1) * page_size
    query = query.order_by(Content.publish_time.desc().nulls_last(), Content.fetched_at.desc()).offset(offset).limit(page_size)

    result = await db.execute(query)
    contents = result.scalars().all()
    items = [ContentResponse(**_serialize_content(c)) for c in contents]
    total_pages = (total + page_size - 1) // page_size

    return ContentListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{content_id}", response_model=ContentResponse)
async def get_content(
    content_id: UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """Get a specific content by ID."""
    result = await db.execute(
        select(Content)
        .options(selectinload(Content.source))
        .filter(Content.id == content_id)
    )
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")
    return ContentResponse(**_serialize_content(content))


@router.patch("/{content_id}", response_model=ContentResponse)
async def update_content(
    content_id: UUID,
    content_data: ContentUpdate,
    db: AsyncSession = Depends(get_async_db),
):
    """Update content (mark as read, favorite, archive)."""
    result = await db.execute(
        select(Content)
        .options(selectinload(Content.source))
        .filter(Content.id == content_id)
    )
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    for field, value in content_data.model_dump(exclude_unset=True).items():
        setattr(content, field, value)

    await db.commit()
    await db.refresh(content)
    return ContentResponse(**_serialize_content(content))


@router.post("/{content_id}/read")
async def mark_as_read(
    content_id: UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """Mark content as read."""
    content = await db.scalar(select(Content).filter(Content.id == content_id))
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    content.read_status = True
    await db.commit()
    return {"message": "Content marked as read"}


@router.post("/{content_id}/favorite")
async def toggle_favorite(
    content_id: UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """Toggle content favorite status."""
    content = await db.scalar(select(Content).filter(Content.id == content_id))
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    content.favorited = not content.favorited
    await db.commit()
    return {"message": "Favorite toggled", "favorited": content.favorited}


@router.delete("/{content_id}")
async def delete_content(
    content_id: UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """Delete a content item."""
    content = await db.scalar(select(Content).filter(Content.id == content_id))
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    await db.delete(content)
    await db.commit()
    return {"message": "Content deleted successfully"}
