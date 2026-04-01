"""API routes for monitoring sources."""

import asyncio
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models import Source, Category, AuthConfig
from app.models.source import SourceType
from app.schemas.source import (
    SourceCreate,
    SourceUpdate,
    SourceResponse,
    SourceListResponse,
    SourceBulkImport,
    SourceExport,
)
from app.services.probe_service import ProbeService
from app.features import PODCAST_DISABLED_DETAIL, PODCAST_SOURCES_ENABLED
from app.services.system_settings import get_system_settings_async
from app.utils.datetime import to_iso_z, utcnow_naive
from app.utils.ttl_cache import TTLCache
from app.utils.url import host_matches, normalize_host

router = APIRouter()
_probe_service = ProbeService()
_source_cache = TTLCache(ttl_seconds=30)
MAX_SOURCES_PAGE_SIZE = 200


def _source_type_value(source_type: object) -> str:
    return source_type.value if hasattr(source_type, "value") else str(source_type)


def _ensure_supported_source_type(source_type: object) -> str:
    normalized = _source_type_value(source_type)
    if normalized == "podcast" and not PODCAST_SOURCES_ENABLED:
        raise HTTPException(status_code=409, detail=PODCAST_DISABLED_DETAIL)
    return normalized


def _exclude_disabled_source_types(query):
    if not PODCAST_SOURCES_ENABLED:
        query = query.filter(Source.type != SourceType.PODCAST)
    return query


def _source_is_visible(source: Source) -> bool:
    return PODCAST_SOURCES_ENABLED or _source_type_value(source.type) != "podcast"


def _invalidate_source_cache() -> None:
    _source_cache.invalidate()


def _coerce_limit_int(value, default: int, *, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(min_value, min(max_value, parsed))


async def _resolve_max_sources_limit(db: AsyncSession) -> int:
    settings = await get_system_settings_async(db)
    limits = settings.get("limits") if isinstance(settings, dict) else {}
    limits = limits if isinstance(limits, dict) else {}
    return _coerce_limit_int(limits.get("max_sources"), 200, min_value=1, max_value=5000)


async def _ensure_source_quota(db: AsyncSession, incoming_count: int = 1) -> None:
    incoming = max(0, int(incoming_count or 0))
    if incoming <= 0:
        return

    max_sources = await _resolve_max_sources_limit(db)
    total_result = await db.execute(select(func.count(Source.id)))
    current_total = int(total_result.scalar() or 0)
    projected_total = current_total + incoming
    if projected_total > max_sources:
        remaining = max(0, max_sources - current_total)
        raise HTTPException(
            status_code=409,
            detail=(
                f"监控源数量已达到上限（{max_sources}）。"
                f"当前 {current_total}，最多还能新增 {remaining}。"
            ),
        )


def _normalize_extra_urls(extra_urls: Optional[List[str]]) -> List[str]:
    """Normalize extra URLs (strip/unique/skip primary blanks)."""
    if not extra_urls:
        return []
    seen = set()
    normalized: List[str] = []
    for raw in extra_urls:
        if not raw:
            continue
        candidate = raw.strip()
        if not candidate:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized


def _get_source_urls(source: Source) -> List[str]:
    """Get all configured URLs for a source (primary + extras)."""
    metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
    extras = _normalize_extra_urls(metadata.get("extra_urls"))
    urls = [source.url]
    for u in extras:
        if u != source.url:
            urls.append(u)
    return urls


def _pick_best_probe(results: List[Tuple[str, object]]) -> Tuple[object, Dict[str, str], int]:
    """Pick best probe result from multiple URLs and collect RSS mapping."""
    rss_urls: Dict[str, str] = {}
    ok_count = 0
    status_order = {"ok": 0, "warning": 1, "error": 2, "unknown": 3}

    best_url = ""
    best_result = None
    best_rank = 99
    for url, result in results:
        status = getattr(result, "status", "unknown")
        rank = status_order.get(status, 3)
        if getattr(result, "rss_url", None):
            rss_urls[url] = result.rss_url
        if status == "ok":
            ok_count += 1
        if best_result is None or rank < best_rank:
            best_result = result
            best_rank = rank
            best_url = url

    if best_result is not None:
        source_message = getattr(best_result, "message", "") or ""
        summary = f"可用 URL {ok_count}/{len(results)}"
        best_result.message = f"{summary}；主策略来自 {best_url}。{source_message}".strip("。")
    return best_result, rss_urls, ok_count


async def _find_matching_auth_config_id(db: AsyncSession, url: str) -> Optional[UUID]:
    """Find the first matching auth config by host for website sources."""
    source_host = normalize_host(url)
    if not source_host:
        return None

    result = await db.execute(select(AuthConfig).order_by(AuthConfig.updated_at.desc()))
    configs = result.scalars().all()
    for cfg in configs:
        cfg_host = normalize_host(cfg.site_url)
        if host_matches(source_host, cfg_host):
            return cfg.id
    return None


async def _probe_urls(urls: List[str], source_type: str):
    """Probe one or more URLs and return best result + rss map."""
    tasks = [_probe_service.probe(url, source_type) for url in urls]
    probe_results = await asyncio.gather(*tasks, return_exceptions=True)
    paired = []
    for url, result in zip(urls, probe_results):
        if isinstance(result, Exception):
            continue
        paired.append((url, result))
    if not paired:
        # fallback to probing primary url only
        fallback = await _probe_service.probe(urls[0], source_type)
        return fallback, {}, 0
    return _pick_best_probe(paired)


def _compute_fetch_status(s: Source, probe: dict) -> tuple:
    """Compute the effective fetch_status by combining probe result with actual fetch history.

    Priority:
      1. If the source has recently fetched content successfully → ok
      2. If the source has fetched but also has errors → warning
      3. Fall back to probe result
      4. If nothing is known → unknown
    Returns (status, strategy, message).
    """
    probe_status = probe.get("status", "unknown")
    probe_strategy = probe.get("strategy", "unknown")
    probe_message = probe.get("message", "")
    metadata = s.metadata_ if isinstance(s.metadata_, dict) else {}
    outcome = metadata.get("last_fetch_outcome") if isinstance(metadata.get("last_fetch_outcome"), dict) else {}
    outcome_severity = str(outcome.get("severity") or "").strip().lower()
    outcome_message = str(outcome.get("message") or "").strip()

    has_content = bool(s.last_content_id)
    has_fetched = s.last_fetched_at is not None
    has_errors = s.error_count > 0 and s.last_error

    # Explicit runtime outcome takes precedence once a fetch has happened.
    if has_fetched and outcome_severity == "error":
        return ("error", probe_strategy if probe_strategy != "unknown" else "auto", outcome_message or "最近抓取失败")
    if has_fetched and outcome_severity == "warning":
        return ("warning", probe_strategy if probe_strategy != "unknown" else "auto", outcome_message or "最近抓取部分受限")

    # Actual fetch success overrides probe failure
    if has_content and has_fetched:
        if has_errors:
            return ("warning", probe_strategy if probe_strategy != "unknown" else "auto",
                    f"已成功抓取过内容，但最近有错误: {s.last_error[:60] if s.last_error else ''}")
        return ("ok", probe_strategy if probe_strategy != "unknown" else "auto",
                "已成功抓取内容")

    # Has fetched but never got content.
    # If there is no runtime error, do not mark as hard error even if probe says error.
    # This avoids false red status for paywalled/low-frequency sources that can run
    # successfully but produced no new items in this cycle.
    if has_fetched and not has_content:
        if probe_status == "ok":
            return ("ok", probe_strategy, f"探测可用。{probe_message}")
        if has_errors:
            return ("error", probe_strategy, f"抓取失败: {s.last_error[:60] if s.last_error else ''}")
        return (
            "warning",
            probe_strategy if probe_strategy != "unknown" else "auto",
            f"最近抓取完成但暂无新内容。{probe_message}".strip(),
        )

    # Fall back to probe result
    if probe_status != "unknown":
        return (probe_status, probe_strategy, probe_message)

    return ("unknown", "unknown", "")


def serialize_source(s: Source) -> dict:
    """Serialize a Source object to dict to avoid metadata conflicts."""
    meta = s.metadata_ if isinstance(s.metadata_, dict) else {}
    probe = meta.get("probe", {})
    eff_status, eff_strategy, eff_message = _compute_fetch_status(s, probe)
    return {
        "id": str(s.id),
        "name": s.name,
        "type": s.type.value if hasattr(s.type, 'value') else s.type,
        "url": s.url,
        "extra_urls": _normalize_extra_urls(meta.get("extra_urls")),
        "category_id": str(s.category_id) if s.category_id else None,
        "fetch_interval": s.fetch_interval,
        "enabled": s.enabled,
        "priority": s.priority,
        "auth_required": s.auth_required,
        "auth_config_id": str(s.auth_config_id) if s.auth_config_id else None,
        "last_fetched_at": to_iso_z(s.last_fetched_at),
        "last_content_id": s.last_content_id,
        "last_error": s.last_error,
        "error_count": s.error_count,
        "metadata": meta,
        "fetch_status": eff_status,
        "fetch_strategy": eff_strategy,
        "fetch_status_message": eff_message,
        "probed_at": probe.get("probed_at"),
        "created_at": to_iso_z(s.created_at),
        "updated_at": to_iso_z(s.updated_at),
    }


class ProbeRequest(BaseModel):
    """Request to probe a URL."""
    url: str
    type: str = "website"


class ProbeResponse(BaseModel):
    """Result of a probe."""
    status: str           # ok, warning, error, unknown
    strategy: str         # rss, scrape, js, rsshub, nitter, api, none
    rss_url: Optional[str] = None
    message: str = ""
    sample_count: int = 0


@router.post("/probe", response_model=ProbeResponse)
async def probe_url(req: ProbeRequest):
    """Probe a URL to determine fetch strategy and reachability — without creating a source."""
    _ensure_supported_source_type(req.type)
    result = await _probe_service.probe(req.url, req.type)
    return ProbeResponse(
        status=result.status,
        strategy=result.strategy,
        rss_url=result.rss_url,
        message=result.message,
        sample_count=result.sample_count,
    )


@router.post("")
async def create_source(
    source_data: SourceCreate,
    db: AsyncSession = Depends(get_async_db)
):
    """Create a new monitoring source. Automatically probes for best fetch strategy."""
    _ensure_supported_source_type(source_data.type)
    # URL 去重：同类型同 URL 的源不允许重复创建
    existing = await db.execute(
        select(Source).filter(Source.url == source_data.url, Source.type == source_data.type)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail=f"已存在相同类型和 URL 的监控源")
    await _ensure_source_quota(db, incoming_count=1)

    metadata = dict(source_data.metadata_ or {})

    extra_urls = _normalize_extra_urls(source_data.extra_urls)
    metadata["extra_urls"] = extra_urls

    # Auto-probe to determine fetch strategy
    try:
        all_urls = [source_data.url] + [u for u in extra_urls if u != source_data.url]
        probe_result, rss_urls, _ = await _probe_urls(all_urls, source_data.type)
        metadata["probe"] = probe_result.to_dict()
        if source_data.type == "x" and probe_result.strategy in {"rsshub", "nitter", "api"}:
            metadata["strategy"] = probe_result.strategy
        if rss_urls:
            metadata["rss_urls"] = rss_urls
        # Keep backward-compatible primary RSS field.
        if source_data.url in rss_urls:
            metadata["rss_url"] = rss_urls[source_data.url]
        elif probe_result.rss_url and "rss_url" not in metadata:
            metadata["rss_url"] = probe_result.rss_url
    except Exception:
        metadata["probe"] = {"status": "unknown", "message": "探测失败", "probed_at": None}

    auth_required = source_data.auth_required
    auth_config_id = source_data.auth_config_id
    source_type = _source_type_value(source_data.type)
    if source_type == "website" and auth_required and not auth_config_id:
        matched_auth_id = await _find_matching_auth_config_id(db, source_data.url)
        if matched_auth_id:
            auth_config_id = matched_auth_id

    source = Source(
        name=source_data.name,
        type=source_data.type,
        url=source_data.url,
        category_id=source_data.category_id,
        fetch_interval=source_data.fetch_interval,
        enabled=source_data.enabled,
        priority=source_data.priority,
        auth_required=auth_required,
        auth_config_id=auth_config_id,
        metadata_=metadata,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    _invalidate_source_cache()
    return serialize_source(source)


@router.get("")
async def list_sources(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_SOURCES_PAGE_SIZE),
    type: Optional[str] = None,
    category_id: Optional[UUID] = None,
    enabled: Optional[bool] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db)
):
    """List all monitoring sources with pagination and filters."""
    if type == "podcast" and not PODCAST_SOURCES_ENABLED:
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}

    cache_key = (
        f"sources:page={page}:size={page_size}:type={type or ''}:"
        f"category={category_id or ''}:enabled={enabled!r}:search={search or ''}"
    )
    cached = _source_cache.get(cache_key)
    if cached is not None:
        return cached

    query = _exclude_disabled_source_types(select(Source))
    count_query = _exclude_disabled_source_types(select(func.count(Source.id)))
    
    # Apply filters
    if type:
        query = query.filter(Source.type == type)
        count_query = count_query.filter(Source.type == type)
    
    if category_id:
        query = query.filter(Source.category_id == category_id)
        count_query = count_query.filter(Source.category_id == category_id)
    
    if enabled is not None:
        query = query.filter(Source.enabled == enabled)
        count_query = count_query.filter(Source.enabled == enabled)
    
    if search:
        search_filter = Source.name.ilike(f"%{search}%")
        query = query.filter(search_filter)
        count_query = count_query.filter(search_filter)
    
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # Apply pagination
    offset = (page - 1) * page_size
    query = query.order_by(Source.priority.desc(), Source.name).offset(offset).limit(page_size)
    
    result = await db.execute(query)
    sources = result.scalars().all()
    
    total_pages = (total + page_size - 1) // page_size
    
    payload = {
        "items": [serialize_source(s) for s in sources],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }
    return _source_cache.set(cache_key, payload)


# NOTE: These routes MUST be before /{source_id} routes to avoid path parameter conflicts
@router.post("/bulk-import")
async def bulk_import_sources(
    import_data: SourceBulkImport,
    db: AsyncSession = Depends(get_async_db)
):
    """Bulk import multiple sources."""
    for source_data in import_data.sources or []:
        _ensure_supported_source_type(source_data.type)
    incoming_count = len(import_data.sources or [])
    await _ensure_source_quota(db, incoming_count=incoming_count)

    created_ids = []
    
    for source_data in import_data.sources:
        # Ensure metadata is a proper dict
        metadata = source_data.metadata_ if source_data.metadata_ else {}
        if not isinstance(metadata, dict):
            metadata = {}
        
        extra_urls = _normalize_extra_urls(source_data.extra_urls)
        metadata["extra_urls"] = extra_urls

        source = Source(
            name=source_data.name,
            type=source_data.type,
            url=source_data.url,
            category_id=source_data.category_id,
            fetch_interval=source_data.fetch_interval,
            enabled=source_data.enabled,
            priority=source_data.priority,
            auth_required=source_data.auth_required,
            auth_config_id=source_data.auth_config_id,
            metadata_=metadata,
        )
        db.add(source)
        await db.flush()  # Get the ID immediately
        created_ids.append(source.id)
    
    await db.commit()
    _invalidate_source_cache()
    
    # Re-fetch all created sources to get properly loaded objects
    result = await db.execute(
        select(Source).filter(Source.id.in_(created_ids))
    )
    created_sources = result.scalars().all()
    
    return [serialize_source(s) for s in created_sources]


@router.get("/export")
async def export_sources(
    db: AsyncSession = Depends(get_async_db)
):
    """Export all sources configuration."""
    from datetime import datetime
    
    result = await db.execute(_exclude_disabled_source_types(select(Source)))
    sources = result.scalars().all()
    
    return {
        "sources": [serialize_source(s) for s in sources],
        "exported_at": to_iso_z(utcnow_naive())
    }


@router.get("/{source_id}")
async def get_source(
    source_id: UUID,
    db: AsyncSession = Depends(get_async_db)
):
    """Get a specific source by ID."""
    result = await db.execute(select(Source).filter(Source.id == source_id))
    source = result.scalar_one_or_none()
    
    if not source or not _source_is_visible(source):
        raise HTTPException(status_code=404, detail="Source not found")
    
    return serialize_source(source)


@router.patch("/{source_id}")
async def update_source(
    source_id: UUID,
    source_data: SourceUpdate,
    db: AsyncSession = Depends(get_async_db)
):
    """Update a monitoring source."""
    result = await db.execute(select(Source).filter(Source.id == source_id))
    source = result.scalar_one_or_none()
    
    if not source or not _source_is_visible(source):
        raise HTTPException(status_code=404, detail="Source not found")
    
    # Update only provided fields
    update_data = source_data.model_dump(exclude_unset=True)
    extra_urls = update_data.pop("extra_urls", None)
    metadata_patch = update_data.pop("metadata_", None)

    target_type = update_data.get("type")
    if target_type is None:
        target_type = _source_type_value(source.type)
    _ensure_supported_source_type(target_type)
    target_url = update_data.get("url", source.url)
    target_auth_required = update_data.get("auth_required", source.auth_required)
    target_auth_config_id = update_data.get("auth_config_id", source.auth_config_id)

    # Auto-bind auth config when paywall is enabled but source has no explicit auth_config_id.
    # Respect explicit disable request (auth_required=false).
    explicit_disable = ("auth_required" in update_data and update_data.get("auth_required") is False)
    if (
        str(target_type) == "website"
        and bool(target_auth_required)
        and not target_auth_config_id
        and not explicit_disable
    ):
        matched_auth_id = await _find_matching_auth_config_id(db, target_url)
        if matched_auth_id:
            update_data["auth_config_id"] = matched_auth_id
            update_data["auth_required"] = True

    if metadata_patch is not None:
        merged_metadata = dict(source.metadata_ or {})
        merged_metadata.update(metadata_patch)
        source.metadata_ = merged_metadata

    if extra_urls is not None:
        normalized = _normalize_extra_urls(extra_urls)
        merged_metadata = dict(source.metadata_ or {})
        merged_metadata["extra_urls"] = normalized
        source.metadata_ = merged_metadata

    for field, value in update_data.items():
        setattr(source, field, value)
    
    await db.commit()
    await db.refresh(source)
    _invalidate_source_cache()
    return serialize_source(source)


@router.delete("/{source_id}")
async def delete_source(
    source_id: UUID,
    db: AsyncSession = Depends(get_async_db)
):
    """Delete a monitoring source."""
    result = await db.execute(select(Source).filter(Source.id == source_id))
    source = result.scalar_one_or_none()
    
    if not source or not _source_is_visible(source):
        raise HTTPException(status_code=404, detail="Source not found")
    
    await db.delete(source)
    await db.commit()
    _invalidate_source_cache()
    
    return {"message": "Source deleted successfully"}


@router.post("/fetch-all")
async def trigger_fetch_all(
    db: AsyncSession = Depends(get_async_db)
):
    """Manually trigger a fetch for all active sources."""
    result = await db.execute(_exclude_disabled_source_types(select(Source).filter(Source.enabled == True)))
    sources = result.scalars().all()

    if not sources:
        return {"message": "No active sources to fetch", "source_count": 0}

    from app.tasks.fetch_tasks import fetch_all_sources
    asyncio.create_task(fetch_all_sources(manual_trigger=True))

    return {
        "message": "Fetch all dispatched",
        "source_count": len(sources),
    }


@router.post("/{source_id}/fetch")
async def trigger_fetch(
    source_id: UUID,
    db: AsyncSession = Depends(get_async_db)
):
    """Manually trigger a fetch for a specific source."""
    result = await db.execute(select(Source).filter(Source.id == source_id))
    source = result.scalar_one_or_none()

    if not source or not _source_is_visible(source):
        raise HTTPException(status_code=404, detail="Source not found")

    from app.background import fetch_lock
    from app.tasks.fetch_tasks import fetch_source

    if fetch_lock.is_locked(str(source_id)):
        return {
            "message": "Fetch already running",
            "source_id": str(source_id),
        }

    asyncio.create_task(fetch_source(str(source_id), manual_trigger=True))

    return {
        "message": "Fetch task dispatched",
        "source_id": str(source_id),
    }


@router.post("/{source_id}/probe")
async def probe_source(
    source_id: UUID,
    db: AsyncSession = Depends(get_async_db)
):
    """Re-probe an existing source to update its fetch status."""
    result = await db.execute(select(Source).filter(Source.id == source_id))
    source = result.scalar_one_or_none()
    if not source or not _source_is_visible(source):
        raise HTTPException(status_code=404, detail="Source not found")

    stype = _ensure_supported_source_type(source.type)
    urls = _get_source_urls(source)
    probe_result, rss_urls, _ = await _probe_urls(urls, stype)

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


@router.post("/probe-all")
async def probe_all_sources(
    db: AsyncSession = Depends(get_async_db)
):
    """Probe all enabled sources and update their fetch status."""
    result = await db.execute(_exclude_disabled_source_types(select(Source).filter(Source.enabled == True)))
    sources = result.scalars().all()

    if not sources:
        return {"message": "No sources to probe", "total": 0}

    updated = 0
    for s in sources:
        stype = _ensure_supported_source_type(s.type)
        urls = _get_source_urls(s)
        try:
            probe_result, rss_urls, _ = await _probe_urls(urls, stype)
        except Exception:
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

    return {"message": f"Probed {updated} sources", "total": updated}
