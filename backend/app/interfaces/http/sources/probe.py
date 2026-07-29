# backend/app/api/sources/probe.py
"""Probe routes: probe_url, probe_source, probe_all_sources."""

import asyncio
from typing import Any, Dict, List, Optional
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


async def _web_clean_probe_metadata(source: Source, cookies: Dict[str, str]) -> dict[str, Any] | None:
    """Validate a configured template and return a body-free clean preview."""
    source_metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
    raw_template = source_metadata.get("web_clean_template")
    if raw_template is None:
        return None
    if not isinstance(raw_template, dict):
        return {
            "template_configured": True,
            "template_valid": False,
            "template_validation_errors": ["web_clean_template must be an object"],
        }

    from app.domains.fetch.web_clean import CleanInput, WebDocumentExtractor
    from app.domains.fetch.web_clean.templates import TemplateValidationError, validate_template
    from app.domains.sources.probe.service import ProbeService
    from app.config import get_settings

    try:
        template = validate_template(raw_template)
    except (TemplateValidationError, TypeError, ValueError) as exc:
        errors = list(getattr(exc, "errors", (str(exc),)))
        return {
            "template_configured": True,
            "template_valid": False,
            "template_validation_errors": [str(item)[:300] for item in errors[:8]],
        }

    result: dict[str, Any] = {
        "template_configured": True,
        "template_valid": True,
        "template_id": template.id,
        "template_validation_errors": [],
    }
    settings = get_settings()
    try:
        html = await ProbeService().fetch_html(
            source.url,
            cookies=cookies,
            timeout=max(1, min(15, int(settings.pim_web_clean_timeout_ms / 1000) + 1)),
        )
        if not html:
            result["preview_error"] = "网页可探测，但未取得可用于清洗预览的 HTML"
            return result
        clean = await asyncio.wait_for(
            WebDocumentExtractor().extract(
                CleanInput(
                    url=source.url,
                    raw_html=html,
                    source_id=str(source.id),
                    source_metadata=source_metadata,
                ),
                max_html_bytes=settings.pim_web_clean_max_html_bytes,
            ),
            timeout=settings.pim_web_clean_timeout_ms / 1000,
        )
        result["preview"] = {
            "extraction_method": clean.extraction_method,
            "template_id": clean.template_id,
            "quality_status": clean.quality_status,
            "quality_score": round(float(clean.quality_score), 4),
            "text_chars": len(clean.article_text),
            "paragraph_count": clean.to_metadata(include_trace=False).get("paragraph_count", 0),
            "blocked": clean.quality_status in {"blocked", "login_required", "bot_wall", "captcha"},
        }
    except asyncio.TimeoutError:
        result["preview_error"] = "网页清洗预览超时"
    except (ValueError, TypeError, RuntimeError) as exc:
        result["preview_error"] = str(exc)[:300]
    return result


@router.post("/probe", response_model=ProbeResponse)
async def probe_url(req: ProbeRequest):
    _ensure_supported_source_type(req.type)
    from app.domains.sources.probe.service import ProbeService
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
    if stype == "website":
        web_clean_probe = await _web_clean_probe_metadata(source, cookies)
        if web_clean_probe is not None:
            meta["web_clean_probe"] = web_clean_probe
    source.metadata_ = meta
    await db.commit()
    await db.refresh(source)
    _invalidate_source_cache()
    return serialize_source(source)
