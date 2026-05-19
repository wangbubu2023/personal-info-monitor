# backend/app/api/sources/fetch_import.py
"""Fetch trigger and bulk import routes."""

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models import Source
from app.schemas.source import SourceBulkImport
from app.utils.logger import get_logger
from ._helpers import (
    _ensure_supported_source_type,
    _source_type_value,
    _source_is_visible,
    _ensure_source_quota,
    _exclude_disabled_source_types,
    _normalize_extra_urls,
    _invalidate_source_cache,
    find_duplicate_source_by_normalized_url,
    serialize_source,
)
from app.utils.url import normalize_source_url_for_dedupe

logger = get_logger(__name__)
router = APIRouter()


@router.post("/bulk-import")
async def bulk_import_sources(import_data: SourceBulkImport, db: AsyncSession = Depends(get_async_db)):
    sources_list = import_data.sources or []
    seen_batch: set[tuple[str, str]] = set()
    to_create: list = []
    skipped = 0

    for source_data in sources_list:
        _ensure_supported_source_type(source_data.type)
        norm = normalize_source_url_for_dedupe(source_data.url)
        st = _source_type_value(source_data.type)
        key = (st, norm)
        if key in seen_batch:
            skipped += 1
            continue
        if await find_duplicate_source_by_normalized_url(db, source_data.url, source_data.type):
            skipped += 1
            continue
        seen_batch.add(key)
        to_create.append(source_data)

    await _ensure_source_quota(db, incoming_count=len(to_create))

    created_ids = []
    for source_data in to_create:
        metadata = dict(source_data.metadata_ or {}) if source_data.metadata_ else {}
        extra_urls = _normalize_extra_urls(source_data.extra_urls)
        metadata["extra_urls"] = extra_urls
        source = Source(
            name=source_data.name, type=source_data.type, url=source_data.url,
            fetch_interval=source_data.fetch_interval,
            enabled=source_data.enabled,
            auth_required=source_data.auth_required, auth_config_id=source_data.auth_config_id,
            metadata_=metadata,
        )
        db.add(source)
        await db.flush()
        created_ids.append(source.id)
    await db.commit()
    _invalidate_source_cache()

    if not created_ids:
        return {"created": [], "skipped_duplicates": skipped}

    result = await db.execute(select(Source).filter(Source.id.in_(created_ids)))
    created_sources = result.scalars().all()
    return {
        "created": [serialize_source(s) for s in created_sources],
        "skipped_duplicates": skipped,
    }


@router.post("/fetch-all")
async def trigger_fetch_all(db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(_exclude_disabled_source_types(select(Source).filter(Source.enabled == True)))
    sources = result.scalars().all()
    if not sources:
        return {"message": "No active sources to fetch", "source_count": 0}
    from app.tasks.fetch_tasks import fetch_all_sources
    asyncio.create_task(fetch_all_sources(manual_trigger=True))
    return {"message": "Fetch all dispatched", "source_count": len(sources)}


@router.post("/{source_id}/fetch")
async def trigger_fetch(source_id: UUID, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Source).filter(Source.id == source_id))
    source = result.scalar_one_or_none()
    if not source or not _source_is_visible(source):
        raise HTTPException(status_code=404, detail="Source not found")
    from app.background import fetch_lock
    from app.tasks.fetch_tasks import fetch_source
    if fetch_lock.is_locked(str(source_id)):
        return {"message": "Fetch already running", "source_id": str(source_id)}
    asyncio.create_task(fetch_source(str(source_id), manual_trigger=True))
    return {"message": "Fetch task dispatched", "source_id": str(source_id)}
