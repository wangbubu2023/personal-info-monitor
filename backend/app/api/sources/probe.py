# backend/app/api/sources/probe.py
"""Probe routes: probe_url, probe_source, probe_all_sources."""

from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from urllib.parse import urlparse

from app.utils.url import normalize_source_url_input
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models import Source
from app.utils.logger import get_logger
from . import _helpers
from ._helpers import (
    _ensure_supported_source_type,
    _exclude_disabled_source_types,
    _get_source_urls,
    _invalidate_source_cache,
    _load_source_probe_cookies,
    _source_is_visible,
    serialize_source,
)

logger = get_logger(__name__)
router = APIRouter()


class ProbeRequest(BaseModel):
    url: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        description="HTTP(S) URL to probe",
    )
    type: str = "website"

    @field_validator("url")
    @classmethod
    def normalize_probe_url(cls, v: str) -> str:
        v = normalize_source_url_input(v)
        if not v or not urlparse(v).netloc:
            raise ValueError("URL must include a valid host")
        return v


class ProbeResponse(BaseModel):
    status: str
    strategy: str
    rss_url: Optional[str] = None
    message: str = ""
    sample_count: int = 0


@router.post("/probe", response_model=ProbeResponse)
async def probe_url(req: ProbeRequest):
    _ensure_supported_source_type(req.type)
    from app.services.probe_service import ProbeService
    result = await ProbeService().probe(req.url, req.type)
    return ProbeResponse(status=result.status, strategy=result.strategy,
                          rss_url=result.rss_url, message=result.message,
                          sample_count=result.sample_count)


@router.post("/probe-all")
async def probe_all_sources(db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(_exclude_disabled_source_types(select(Source).filter(Source.enabled == True)))
    sources = result.scalars().all()
    if not sources:
        return {"message": "No sources to probe", "total": 0, "failed_items": []}

    updated = 0
    failed_items: List[Dict[str, str]] = []
    for s in sources:
        stype = _ensure_supported_source_type(s.type)
        urls = _get_source_urls(s)
        cookies = await _load_source_probe_cookies(db, s)
        try:
            probe_result, rss_urls, _ = await _helpers._probe_urls(urls, stype, cookies=cookies)
        except Exception as exc:
            logger.warning("Batch probe failed for source %s: %s", s.id, exc)
            failed_items.append({"id": str(s.id), "error": str(exc)[:200]})
            continue
        meta = dict(s.metadata_ or {})
        meta["probe"] = probe_result.to_dict()
        if stype == "x" and probe_result.strategy in {"rsshub", "nitter", "api"}:
            meta["strategy"] = probe_result.strategy
        if rss_urls:
            meta["rss_urls"] = rss_urls
        if s.url in rss_urls:
            meta["rss_url"] = rss_urls[s.url]
        elif probe_result.rss_url:
            meta["rss_url"] = probe_result.rss_url
        s.metadata_ = meta
        updated += 1
    await db.commit()
    _invalidate_source_cache()
    return {"message": f"Probed {updated} sources", "total": updated, "failed_items": failed_items}


@router.post("/{source_id}/probe")
async def probe_source(source_id: UUID, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Source).filter(Source.id == source_id))
    source = result.scalar_one_or_none()
    if not source or not _source_is_visible(source):
        raise HTTPException(status_code=404, detail="Source not found")

    stype = _ensure_supported_source_type(source.type)
    urls = _get_source_urls(source)
    cookies = await _load_source_probe_cookies(db, source)
    probe_result, rss_urls, _ = await _helpers._probe_urls(urls, stype, cookies=cookies)

    meta = dict(source.metadata_ or {})
    meta["probe"] = probe_result.to_dict()
    if stype == "x" and probe_result.strategy in {"rsshub", "nitter", "api"}:
        meta["strategy"] = probe_result.strategy
    if rss_urls:
        meta["rss_urls"] = rss_urls
    if source.url in rss_urls:
        meta["rss_url"] = rss_urls[source.url]
    elif probe_result.rss_url:
        meta["rss_url"] = probe_result.rss_url
    source.metadata_ = meta
    await db.commit()
    await db.refresh(source)
    _invalidate_source_cache()
    return serialize_source(source)
