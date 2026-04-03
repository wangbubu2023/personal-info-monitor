# backend/app/api/sources/mutation.py
"""Write source routes: create, update, delete."""

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models import Source
from app.schemas.source import SourceCreate, SourceUpdate
from app.utils.logger import get_logger
from ._helpers import (
    _ensure_supported_source_type,
    _source_type_value,
    _source_is_visible,
    _ensure_source_quota,
    _normalize_extra_urls,
    _find_matching_auth_config_id,
    _invalidate_source_cache,
    serialize_source,
)

logger = get_logger(__name__)
router = APIRouter()


@router.post("")
async def create_source(source_data: SourceCreate, db: AsyncSession = Depends(get_async_db)):
    _ensure_supported_source_type(source_data.type)
    existing = await db.execute(
        select(Source).filter(Source.url == source_data.url, Source.type == source_data.type)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="已存在相同类型和 URL 的监控源")
    await _ensure_source_quota(db, incoming_count=1)

    metadata = dict(source_data.metadata_ or {})
    extra_urls = _normalize_extra_urls(source_data.extra_urls)
    metadata["extra_urls"] = extra_urls

    try:
        import app.api.sources as _pkg
        all_urls = [source_data.url] + [u for u in extra_urls if u != source_data.url]
        probe_result, rss_urls, _ = await _pkg._probe_urls(all_urls, source_data.type)
        metadata["probe"] = probe_result.to_dict()
        if source_data.type == "x" and probe_result.strategy in {"rsshub", "nitter", "api"}:
            metadata["strategy"] = probe_result.strategy
        if rss_urls:
            metadata["rss_urls"] = rss_urls
        if source_data.url in rss_urls:
            metadata["rss_url"] = rss_urls[source_data.url]
        elif probe_result.rss_url and "rss_url" not in metadata:
            metadata["rss_url"] = probe_result.rss_url
    except Exception as exc:
        logger.warning("Probe failed for source %s: %s", source_data.url, exc)
        metadata["probe"] = {"status": "failed", "strategy": "unknown", "rss_url": None,
                              "message": str(exc)[:200], "sample_count": 0, "probed_at": None}

    auth_required = source_data.auth_required
    auth_config_id = source_data.auth_config_id
    if _source_type_value(source_data.type) == "website" and auth_required and not auth_config_id:
        matched_auth_id = await _find_matching_auth_config_id(db, source_data.url)
        if matched_auth_id:
            auth_config_id = matched_auth_id

    source = Source(
        name=source_data.name, type=source_data.type, url=source_data.url,
        category_id=source_data.category_id, fetch_interval=source_data.fetch_interval,
        enabled=source_data.enabled, priority=source_data.priority,
        auth_required=auth_required, auth_config_id=auth_config_id, metadata_=metadata,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    _invalidate_source_cache()
    return serialize_source(source)


@router.patch("/{source_id}")
async def update_source(source_id: UUID, source_data: SourceUpdate, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Source).filter(Source.id == source_id))
    source = result.scalar_one_or_none()
    if not source or not _source_is_visible(source):
        raise HTTPException(status_code=404, detail="Source not found")

    update_data = source_data.model_dump(exclude_unset=True)
    extra_urls = update_data.pop("extra_urls", None)
    metadata_patch = update_data.pop("metadata_", None)

    target_type = update_data.get("type") or _source_type_value(source.type)
    _ensure_supported_source_type(target_type)
    target_url = update_data.get("url", source.url)
    target_auth_required = update_data.get("auth_required", source.auth_required)
    target_auth_config_id = update_data.get("auth_config_id", source.auth_config_id)
    explicit_disable = ("auth_required" in update_data and update_data.get("auth_required") is False)

    if (str(target_type) == "website" and bool(target_auth_required)
            and not target_auth_config_id and not explicit_disable):
        matched_auth_id = await _find_matching_auth_config_id(db, target_url)
        if matched_auth_id:
            update_data["auth_config_id"] = matched_auth_id
            update_data["auth_required"] = True

    if metadata_patch is not None:
        merged = dict(source.metadata_ or {})
        merged.update(metadata_patch)
        source.metadata_ = merged
    if extra_urls is not None:
        merged = dict(source.metadata_ or {})
        merged["extra_urls"] = _normalize_extra_urls(extra_urls)
        source.metadata_ = merged

    for field, value in update_data.items():
        setattr(source, field, value)
    await db.commit()
    await db.refresh(source)
    _invalidate_source_cache()
    return serialize_source(source)


@router.delete("/{source_id}")
async def delete_source(source_id: UUID, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Source).filter(Source.id == source_id))
    source = result.scalar_one_or_none()
    if not source or not _source_is_visible(source):
        raise HTTPException(status_code=404, detail="Source not found")
    await db.delete(source)
    await db.commit()
    _invalidate_source_cache()
    return {"message": "Source deleted successfully"}
