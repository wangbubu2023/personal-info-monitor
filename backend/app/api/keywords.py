"""API routes for keyword management."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models import Keyword
from app.schemas.keyword import (
    KeywordCreate,
    KeywordUpdate,
    KeywordResponse,
    KeywordListResponse,
)
from app.utils.ttl_cache import TTLCache

router = APIRouter()
_keyword_cache = TTLCache(ttl_seconds=30)


def _invalidate_keyword_cache() -> None:
    _keyword_cache.invalidate()


@router.post("", response_model=KeywordResponse)
async def create_keyword(
    keyword_data: KeywordCreate,
    db: AsyncSession = Depends(get_async_db)
):
    """Create a new keyword."""
    keyword = Keyword(
        keyword=keyword_data.keyword,
        description=keyword_data.description,
        match_type=keyword_data.match_type,
        case_sensitive=keyword_data.case_sensitive,
        notify=keyword_data.notify,
        notify_email=keyword_data.notify_email,
        color=keyword_data.color,
        enabled=keyword_data.enabled,
    )
    db.add(keyword)
    await db.commit()
    await db.refresh(keyword)
    _invalidate_keyword_cache()
    return keyword


@router.get("", response_model=KeywordListResponse)
async def list_keywords(
    enabled: bool = None,
    db: AsyncSession = Depends(get_async_db)
):
    """List all keywords."""
    cache_key = f"keywords:enabled={enabled!r}"
    cached = _keyword_cache.get(cache_key)
    if cached is not None:
        return cached

    query = select(Keyword)
    count_query = select(func.count(Keyword.id))
    
    if enabled is not None:
        query = query.filter(Keyword.enabled == enabled)
        count_query = count_query.filter(Keyword.enabled == enabled)
    
    query = query.order_by(Keyword.created_at.desc())
    
    result = await db.execute(query)
    keywords = result.scalars().all()
    
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    payload = KeywordListResponse(items=keywords, total=total).model_dump(mode="json")
    return _keyword_cache.set(cache_key, payload)


@router.get("/{keyword_id}", response_model=KeywordResponse)
async def get_keyword(
    keyword_id: UUID,
    db: AsyncSession = Depends(get_async_db)
):
    """Get a specific keyword by ID."""
    result = await db.execute(select(Keyword).filter(Keyword.id == keyword_id))
    keyword = result.scalar_one_or_none()
    
    if not keyword:
        raise HTTPException(status_code=404, detail="Keyword not found")
    
    return keyword


@router.patch("/{keyword_id}", response_model=KeywordResponse)
async def update_keyword(
    keyword_id: UUID,
    keyword_data: KeywordUpdate,
    db: AsyncSession = Depends(get_async_db)
):
    """Update a keyword."""
    result = await db.execute(select(Keyword).filter(Keyword.id == keyword_id))
    keyword = result.scalar_one_or_none()
    
    if not keyword:
        raise HTTPException(status_code=404, detail="Keyword not found")
    
    # Update only provided fields
    update_data = keyword_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(keyword, field, value)
    
    await db.commit()
    await db.refresh(keyword)
    _invalidate_keyword_cache()
    return keyword


@router.delete("/{keyword_id}")
async def delete_keyword(
    keyword_id: UUID,
    db: AsyncSession = Depends(get_async_db)
):
    """Delete a keyword."""
    result = await db.execute(select(Keyword).filter(Keyword.id == keyword_id))
    keyword = result.scalar_one_or_none()
    
    if not keyword:
        raise HTTPException(status_code=404, detail="Keyword not found")
    
    await db.delete(keyword)
    await db.commit()
    _invalidate_keyword_cache()
    
    return {"message": "Keyword deleted successfully"}
