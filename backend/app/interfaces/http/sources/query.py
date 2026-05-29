# backend/app/api/sources/query.py
"""Read-only source routes: list, get, export."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models import Content, Source
from app.features import PODCAST_SOURCES_ENABLED
from app.utils.datetime import to_iso_z, utcnow_naive
from app.utils.logger import get_logger
from ._helpers import (
    _exclude_disabled_source_types,
    _source_is_visible,
    _source_cache,
    MAX_SOURCES_PAGE_SIZE,
    serialize_source,
)

logger = get_logger(__name__)
router = APIRouter()


@router.get("")
async def list_sources(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_SOURCES_PAGE_SIZE),
    type: Optional[str] = None,
    enabled: Optional[bool] = None,
    search: Optional[str] = None,
    scope: Optional[str] = None,
    sort_by: Optional[str] = Query(None, pattern="^(name|content_count)$"),
    sort_order: Optional[str] = Query(None, pattern="^(ascend|descend|asc|desc)$"),
    db: AsyncSession = Depends(get_async_db),
):
    if type == "podcast" and not PODCAST_SOURCES_ENABLED:
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}

    cache_key = (
        f"sources:page={page}:size={page_size}:type={type or ''}:"
        f"enabled={enabled!r}:search={search or ''}:"
        f"sort_by={sort_by or ''}:sort_order={sort_order or ''}"
    )
    cached = _source_cache.get(cache_key)
    if cached is not None:
        return cached

    content_counts = (
        select(Content.source_id, func.count(Content.id).label("content_count"))
        .group_by(Content.source_id)
        .subquery()
    )
    content_count_expr = func.coalesce(content_counts.c.content_count, 0).label("content_count")

    query = _exclude_disabled_source_types(
        select(Source, content_count_expr).outerjoin(
            content_counts,
            content_counts.c.source_id == Source.id,
        )
    )
    count_query = _exclude_disabled_source_types(select(func.count(Source.id)))

    if type:
        query = query.filter(Source.type == type)
        count_query = count_query.filter(Source.type == type)
    if enabled is not None:
        query = query.filter(Source.enabled == enabled)
        count_query = count_query.filter(Source.enabled == enabled)
    if search:
        search_filter = Source.name.ilike(f"%{search}%")
        query = query.filter(search_filter)
        count_query = count_query.filter(search_filter)

    total_result = await db.execute(count_query)
    total = total_result.scalar()
    offset = (page - 1) * page_size
    if sort_by == "content_count":
        order_expr = content_count_expr.desc() if sort_order in {"descend", "desc"} else content_count_expr.asc()
        query = query.order_by(order_expr, Source.name)
    else:
        order_expr = Source.name.desc() if sort_order in {"descend", "desc"} else Source.name.asc()
        query = query.order_by(order_expr)
    query = query.offset(offset).limit(page_size)
    result = await db.execute(query)
    rows = result.all()
    total_pages = (total + page_size - 1) // page_size

    payload = {
        "items": [serialize_source(source, content_count=content_count) for source, content_count in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }
    return _source_cache.set(cache_key, payload)


@router.get("/export")
async def export_sources(db: AsyncSession = Depends(get_async_db)):
    content_counts = (
        select(Content.source_id, func.count(Content.id).label("content_count"))
        .group_by(Content.source_id)
        .subquery()
    )
    content_count_expr = func.coalesce(content_counts.c.content_count, 0).label("content_count")
    result = await db.execute(
        _exclude_disabled_source_types(
            select(Source, content_count_expr).outerjoin(
                content_counts,
                content_counts.c.source_id == Source.id,
            )
        ).order_by(Source.name)
    )
    rows = result.all()
    return {
        "sources": [serialize_source(source, content_count=content_count) for source, content_count in rows],
        "exported_at": to_iso_z(utcnow_naive()),
    }


@router.get("/{source_id}")
async def get_source(source_id: UUID, db: AsyncSession = Depends(get_async_db)):
    content_counts = (
        select(Content.source_id, func.count(Content.id).label("content_count"))
        .group_by(Content.source_id)
        .subquery()
    )
    content_count_expr = func.coalesce(content_counts.c.content_count, 0).label("content_count")
    result = await db.execute(
        select(Source, content_count_expr)
        .outerjoin(content_counts, content_counts.c.source_id == Source.id)
        .filter(Source.id == source_id)
    )
    row = result.one_or_none()
    source = row[0] if row else None
    if not source or not _source_is_visible(source):
        raise HTTPException(status_code=404, detail="Source not found")
    return serialize_source(source, content_count=row[1])
