# backend/app/api/sources/query.py
"""Read-only source routes: list, get, export."""

from datetime import timedelta
from typing import Optional
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models import BrowserSession, Content, Source, SourceFetchLog
from app.features import PODCAST_SOURCES_ENABLED
from app.utils.datetime import to_iso_z, utcnow_naive
from app.domains.fetch.profile import summarize_profile
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


def _host_from_url(value: str | None) -> str:
    parsed = urlparse(value or "")
    return (parsed.netloc or parsed.path or "").split("@")[-1].split(":")[0].lower()


def _paid_source_metadata(source: Source) -> dict:
    meta = source.metadata_ if isinstance(source.metadata_, dict) else {}
    paid = meta.get("paid_source") if isinstance(meta.get("paid_source"), dict) else {}
    return paid


def _paid_source_discovery(source: Source, paid: dict) -> str:
    if paid.get("discovery"):
        return str(paid.get("discovery"))
    source_type = source.type.value if hasattr(source.type, "value") else str(source.type)
    if source_type == "rss":
        return "RSS"
    if source_type == "website":
        return "网站"
    if source_type == "x":
        return "X"
    return source_type


def _paid_source_body_path(source: Source, paid: dict, session: BrowserSession | None) -> str:
    if paid.get("body_path"):
        return str(paid.get("body_path"))
    if session is not None:
        mode = str(session.session_mode or "")
        if mode == "persistent_profile":
            return "VPS persistent profile"
        if mode == "storage_state":
            return "VPS storage state"
        return "VPS browser session"
    if source.auth_config_id:
        return "VPS auth config"
    return "RSS summary / 原文链接"


def _paid_source_recovery_action(source: Source, session: BrowserSession | None, paid: dict) -> str:
    if paid.get("recovery_action"):
        return str(paid.get("recovery_action"))
    reason = source.session_health_reason or source.fetch_failure_code or source.last_fetch_outcome_code
    if reason in {"expired", "login_required", "auth_required_but_missing"}:
        return "重新登录并校验验收 URL"
    if reason in {"captcha", "bot_wall"}:
        return "切换本机抓取或降级 RSS-only"
    if session is not None and str(session.status) != "active":
        return "用验收 URL 重新校验会话"
    return "持续每日 canary；失败时按原因处理"


@router.get("/paid-matrix")
async def get_paid_source_matrix(db: AsyncSession = Depends(get_async_db)):
    """Return the paid-source SLO matrix used by ops/product.

    Sources enter the matrix when they require auth, bind an auth config, have
    session health, or explicitly set metadata.paid_source.enabled. It is a
    read-side view over existing source/session/fetch health state; the actual
    canary fetches continue to be recorded by the fetch pipeline.
    """

    result = await db.execute(
        _exclude_disabled_source_types(
            select(Source).where(
                or_(
                    Source.auth_required.is_(True),
                    Source.auth_config_id.isnot(None),
                    Source.session_health_status.isnot(None),
                )
            )
        ).order_by(Source.name)
    )
    sources = list(result.scalars().all())
    explicit_result = await db.execute(
        _exclude_disabled_source_types(select(Source).where(Source.metadata_.isnot(None))).order_by(Source.name)
    )
    seen_ids = {str(source.id) for source in sources}
    for source in explicit_result.scalars().all():
        paid = _paid_source_metadata(source)
        if paid.get("enabled") and str(source.id) not in seen_ids:
            sources.append(source)
            seen_ids.add(str(source.id))

    session_result = await db.execute(select(BrowserSession))
    sessions_by_host = {
        _host_from_url(session.site_host or session.site_url): session for session in session_result.scalars().all()
    }

    items = []
    for source in sources:
        paid = _paid_source_metadata(source)
        host = _host_from_url(source.url)
        session = sessions_by_host.get(host)
        profile = summarize_profile(source)
        log_result = await db.execute(
            select(SourceFetchLog)
            .where(SourceFetchLog.source_id == str(source.id))
            .where(SourceFetchLog.attempted_at >= utcnow_naive() - timedelta(days=7))
            .order_by(SourceFetchLog.attempted_at.desc())
        )
        logs = list(log_result.scalars().all())
        fulltext_ok = sum(max(0, int(log.fulltext_ok or 0)) for log in logs)
        fulltext_total = sum(max(0, int(log.fulltext_total or 0)) for log in logs)
        matrix_success_rate = round(fulltext_ok / fulltext_total, 3) if fulltext_total else None
        profile_fulltext_rate = profile.get("fulltext_success_rate_7d")
        profile_success_rate = (
            profile_fulltext_rate if profile_fulltext_rate is not None else profile.get("success_rate_7d")
        )
        last_success_log = next((log for log in logs if log.outcome == "success"), None)
        last_success = (
            paid.get("last_success_at")
            or (last_success_log.attempted_at.isoformat() + "Z" if last_success_log else None)
            or profile.get("last_success_at")
            or to_iso_z(source.last_fetched_at)
        )
        failure_code = (
            paid.get("failure_code")
            or source.session_health_reason
            or source.fetch_failure_code
            or source.last_fetch_outcome_code
            or profile.get("last_failure_code")
        )
        items.append(
            {
                "source_id": str(source.id),
                "source_name": source.name,
                "source_type": source.type.value if hasattr(source.type, "value") else str(source.type),
                "host": host,
                "discovery": _paid_source_discovery(source, paid),
                "body_path": _paid_source_body_path(source, paid, session),
                "validation_url": paid.get("validation_url") or paid.get("canary_url") or source.url,
                "last_success_at": last_success,
                "success_rate_7d": paid.get(
                    "success_rate_7d",
                    matrix_success_rate if matrix_success_rate is not None else profile_success_rate,
                ),
                "failure_code": failure_code,
                "recovery_action": _paid_source_recovery_action(source, session, paid),
                "session_status": str(session.status.value if session and hasattr(session.status, "value") else session.status) if session else None,
                "session_mode": str(session.session_mode) if session else None,
            }
        )
    return {"items": items, "total": len(items), "generated_at": to_iso_z(utcnow_naive())}


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
