"""API routes for digest generation."""

from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_async_db
from app.models import Content, HourlyDigest
from app.schemas.digest import (
    DigestResponse, DigestCategory, DigestItem,
    HourlyDigestSummary, HourlyDigestDetail,
)
from app.platform.config.system_settings import (
    get_system_settings_async,
    normalize_hourly_digest_window_hours,
)
from app.domains.enrich.hourly.repository import (
    HOURLY_DIGEST_CANDIDATE_LIMIT,
    candidate_ordering,
)
from app.domains.ingest.visibility import visible_content_clause
from app.utils.datetime import local_date_range_to_utc_naive, today_in_user_timezone, to_iso_z, utcnow_naive, user_timezone
from app.utils.logger import get_logger
from app.domains.ingest.quality_metadata import merge_content_quality_metadata
from app.utils.text import strip_html_tags, text_looks_like_embedded_binary

logger = get_logger(__name__)

router = APIRouter()

# 列表预览：最短字符数（与前端 makeDigestBodyPreview 一致）；上限避免列表过长
_DIGEST_SNIPPET_MIN = 12
_DIGEST_SNIPPET_MAX = 280


def _digest_snippet_from_text(raw: Optional[str]) -> Optional[str]:
    """Strip HTML, enforce min length, truncate with word-ish break for dashboard list."""
    if not raw or not str(raw).strip():
        return None
    if text_looks_like_embedded_binary(str(raw)):
        return None
    plain = strip_html_tags(str(raw)).strip()
    if len(plain) < _DIGEST_SNIPPET_MIN:
        return None
    if len(plain) <= _DIGEST_SNIPPET_MAX:
        return plain
    cut = plain[:_DIGEST_SNIPPET_MAX]
    last_space = cut.rfind(" ")
    if last_space > _DIGEST_SNIPPET_MAX // 2:
        cut = cut[:last_space]
    return cut.rstrip() + "…"


def _digest_list_preview(content: Content) -> Optional[str]:
    """Prefer translated summary, then raw summary, then body excerpt."""
    prev = _digest_snippet_from_text(content.translated_summary)
    if prev:
        return prev
    prev = _digest_snippet_from_text(content.summary)
    if prev:
        return prev
    return _digest_snippet_from_text(content.full_content)


def _collect_listing_translation_backfill_ids(contents: list[Content], *, max_items: int = 30) -> list[str]:
    from app.domains.enrich.content.listing_translation import (
        content_needs_listing_translation,
        listing_translation_enabled,
    )

    if not listing_translation_enabled():
        return []

    ids: list[str] = []
    for content in contents:
        if len(ids) >= max_items:
            break
        if content_needs_listing_translation(
            title=content.title or "",
            summary=content.summary,
            translated_title=content.translated_title,
            translated_summary=content.translated_summary,
        ):
            ids.append(str(content.id))
    return ids


def _digest_item_metadata(content: Content) -> dict:
    """Metadata for list cards; refresh quality when body grew after ingest/backfill."""
    metadata = dict(content.metadata_ or {})
    stored = str(metadata.get("fulltext_status") or "").strip()
    body_len = len((content.full_content or "").strip())
    summary_plain = strip_html_tags(
        str(content.translated_summary or content.summary or "")
    ).strip()
    stale_low_tier = stored in {"title_only", "summary_only", "blocked"}
    body_outgrew_label = stale_low_tier and body_len >= 400
    summary_outgrew_title_only = stored == "title_only" and len(summary_plain) >= 50
    if (
        metadata.get("reader_fulltext_backfilled_at")
        or body_outgrew_label
        or summary_outgrew_title_only
    ):
        metadata = merge_content_quality_metadata(
            metadata,
            title=content.title or "",
            full_content=content.full_content,
            summary=content.summary,
            translated_summary=content.translated_summary,
        )
    return metadata


def _digest_item_from_content(content: Content) -> DigestItem:
    body_prev = _digest_list_preview(content)
    metadata = _digest_item_metadata(content)
    source_metadata = (
        content.source.metadata_
        if content.source and isinstance(content.source.metadata_, dict)
        else {}
    )
    if "source_stars" not in metadata and source_metadata.get("source_stars") is not None:
        metadata["source_stars"] = source_metadata.get("source_stars")

    return DigestItem(
        id=content.id,
        source_id=content.source_id,
        source_name=content.source.name if content.source else "Unknown",
        title=content.title,
        translated_title=content.translated_title,
        summary=content.summary,
        translated_summary=content.translated_summary,
        body_preview=body_prev,
        url=content.original_url,
        publish_time=content.publish_time,
        fetched_at=content.fetched_at,
        read_status=content.read_status,
        favorited=content.favorited,
        keyword_matches=content.keyword_matches or [],
        metadata=metadata,
    )


def get_category_key(content_type: str) -> str:
    """Map content type to category key."""
    mapping = {
        "website": "websites",
        "rss": "rss",
        "x": "x_accounts",
        "youtube": "youtube",
        "podcast": "podcasts"
    }
    return mapping.get(content_type, "websites")


def _parse_digest_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Date must use YYYY-MM-DD") from exc


@router.get("", response_model=DigestResponse)
async def get_daily_digest(
    digest_date: Optional[str] = Query(None, alias="date"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    sort: str = Query("time_desc"),
    keyword_ids: Optional[List[UUID]] = Query(None),
    unread_only: bool = False,
    source_types: Optional[List[str]] = Query(None),
    db: AsyncSession = Depends(get_async_db)
):
    """Get daily digest for a specific date."""
    if sort not in {"time_desc", "score_desc"}:
        raise HTTPException(status_code=422, detail="sort must be time_desc or score_desc")

    # Default to today. When date_from/date_to are provided, they define an
    # inclusive local-date range; the legacy date parameter remains a one-day
    # shorthand for existing callers.
    if date_from or date_to:
        start_date = _parse_digest_date(date_from or date_to or "")
        end_date = _parse_digest_date(date_to or date_from or "")
    elif digest_date:
        start_date = _parse_digest_date(digest_date)
        end_date = start_date
    else:
        start_date = today_in_user_timezone()
        end_date = start_date

    if end_date < start_date:
        raise HTTPException(status_code=422, detail="date_to must be on or after date_from")
    
    # Convert business-local date to UTC range to leverage ix_content_fetched_at index.
    day_start, day_end = local_date_range_to_utc_naive(start_date, end_date)

    # Build query
    query = (
        select(Content)
        .options(selectinload(Content.source))
        .filter(Content.fetched_at >= day_start, Content.fetched_at < day_end)
        .filter(visible_content_clause())
    )
    
    # Apply filters
    if unread_only:
        query = query.filter(Content.read_status == False)
    
    if source_types:
        query = query.filter(Content.content_type.in_(source_types))
    
    # Note: keyword_ids filtering would require JSON query which is complex
    # For now, we filter after fetching
    
    if sort == "score_desc":
        query = query.order_by(*candidate_ordering(Content))
    else:
        # 信息流按文章发布时间排序；抓取/入库时间只在发布时间缺失或相同时兜底。
        query = query.order_by(Content.publish_time.desc().nulls_last(), Content.fetched_at.desc())
    
    result = await db.execute(query)
    contents = result.scalars().all()
    
    # Filter by keyword_ids if provided
    if keyword_ids:
        keyword_id_strs = [str(kid) for kid in keyword_ids]
        filtered_contents = []
        for content in contents:
            if content.keyword_matches:
                for match in content.keyword_matches:
                    if match.get("id") in keyword_id_strs:
                        filtered_contents.append(content)
                        break
        contents = filtered_contents
    
    # Build digest response
    response_date = (
        start_date.isoformat()
        if start_date == end_date
        else f"{start_date.isoformat()}..{end_date.isoformat()}"
    )
    digest = DigestResponse(
        date=response_date,
        total_items=len(contents),
        categories={
            "websites": DigestCategory(count=0, items=[]),
            "rss": DigestCategory(count=0, items=[]),
            "x_accounts": DigestCategory(count=0, items=[]),
            "youtube": DigestCategory(count=0, items=[]),
            "podcasts": DigestCategory(count=0, items=[])
        }
    )
    
    for content in contents:
        category_key = get_category_key(content.content_type)
        item = _digest_item_from_content(content)
        digest.categories[category_key].items.append(item)
        digest.categories[category_key].count += 1

    from app.domains.enrich.content.listing_translation import schedule_listing_translation_backfill

    schedule_listing_translation_backfill(_collect_listing_translation_backfill_ids(contents))
    
    return digest


@router.get("/stats")
async def get_digest_stats(
    days: int = Query(7, ge=1, le=30),
    db: AsyncSession = Depends(get_async_db)
):
    """Get digest statistics for the past N days."""
    end_date = today_in_user_timezone()
    start_date = end_date - timedelta(days=days - 1)

    # Convert business-local date range to UTC bounds for index-friendly filtering.
    stats_start_utc, stats_end_utc = local_date_range_to_utc_naive(start_date, end_date)

    # Pull per-day + per-type counts in one pass, then aggregate in Python.
    # On SQLite this collapses two index scans over the same range into one
    # (P3 in the 2026-04-20 audit). The rollup GROUP BY is tiny (days * types)
    # so Python-side reduction costs nothing.
    range_result = await db.execute(
        select(
            func.date(Content.fetched_at).label("date"),
            Content.content_type.label("content_type"),
            func.count(Content.id).label("count"),
        )
        .filter(Content.fetched_at >= stats_start_utc, Content.fetched_at < stats_end_utc)
        .group_by(func.date(Content.fetched_at), Content.content_type)
        .order_by(func.date(Content.fetched_at))
    )
    daily_totals: "dict[str, int]" = {}
    type_totals: "dict[str, int]" = {}
    daily_order: list[str] = []
    for row in range_result.all():
        date_key = row.date.isoformat() if hasattr(row.date, "isoformat") else str(row.date)
        if date_key not in daily_totals:
            daily_totals[date_key] = 0
            daily_order.append(date_key)
        daily_totals[date_key] += int(row.count)
        if row.content_type:
            type_totals[row.content_type] = type_totals.get(row.content_type, 0) + int(row.count)

    # Global unread + favorited counts: one query via conditional aggregation
    # instead of two separate COUNTs.
    totals_row = (
        await db.execute(
            select(
                func.sum(case((Content.read_status == False, 1), else_=0)).label("unread"),
                func.sum(case((Content.favorited == True, 1), else_=0)).label("favorited"),
            )
        )
    ).one()

    return {
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "days": days,
        },
        "daily_counts": [
            {"date": date_key, "count": daily_totals[date_key]} for date_key in daily_order
        ],
        "type_counts": type_totals,
        "unread_count": int(totals_row.unread or 0),
        "favorited_count": int(totals_row.favorited or 0),
    }


def _map_source_type_key(content_type: str) -> str:
    """Map content_type to the frontend source key."""
    mapping = {
        "website": "websites",
        "rss": "rss",
        "x": "x",
        "youtube": "youtube",
        "podcast": "podcasts",
    }
    return mapping.get(content_type, "websites")


def _completed_hour_label_to_utc_window(
    target_date: date,
    hour: int,
    *,
    window_hours: int = 1,
) -> tuple[datetime, datetime]:
    """Map a digest label hour to the completed local-hour window it summarizes."""
    window_hours = max(1, int(window_hours or 1))
    end_local = datetime(target_date.year, target_date.month, target_date.day, hour, tzinfo=user_timezone())
    start_local = end_local - timedelta(hours=window_hours)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


@router.get("/hourly", response_model=List[HourlyDigestSummary])
async def get_hourly_digests(
    digest_date: Optional[str] = Query(None, alias="date"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get a list of hourly digest summaries for a given date.
    Returns hours that have content, with counts and source type breakdowns.
    """
    if digest_date:
        target_date = datetime.strptime(digest_date, "%Y-%m-%d").date()
    else:
        target_date = today_in_user_timezone()
    
    result = await db.execute(
        select(HourlyDigest)
        .filter(HourlyDigest.digest_date == target_date)
        .order_by(HourlyDigest.hour.desc())
    )
    rows = result.scalars().all()

    return [
        HourlyDigestSummary(
            hour=row.hour,
            title=row.title,
            content_count=row.content_count,
            summary=None,
            generated_at=to_iso_z(row.created_at),
            sources={
                "websites": row.content_count,
                "x": 0,
                "youtube": 0,
                "podcasts": 0,
            },
        )
        for row in rows
    ]


@router.get("/hourly/{hour}", response_model=HourlyDigestDetail)
async def get_hourly_digest_detail(
    hour: int,
    digest_date: Optional[str] = Query(None, alias="date"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get detailed digest for a specific hour, including AI-generated summary.
    """
    if digest_date:
        target_date = datetime.strptime(digest_date, "%Y-%m-%d").date()
    else:
        target_date = today_in_user_timezone()
    
    digest_result = await db.execute(
        select(HourlyDigest).filter(
            HourlyDigest.digest_date == target_date,
            HourlyDigest.hour == hour,
        )
    )
    digest_row = digest_result.scalar_one_or_none()

    if not digest_row:
        return HourlyDigestDetail(
            hour=hour,
            date=target_date.isoformat(),
            title=None,
            summary=None,
            content_count=0,
            sources=[],
            event_items=[],
            items=[],
            generated_at=to_iso_z(utcnow_naive()),
        )

    merged = await get_system_settings_async(db)
    window_hours = normalize_hourly_digest_window_hours(merged)
    start_utc, end_utc = _completed_hour_label_to_utc_window(
        target_date,
        hour,
        window_hours=window_hours,
    )
    result = await db.execute(
        select(Content)
        .options(selectinload(Content.source))
        .filter(Content.fetched_at >= start_utc)
        .filter(Content.fetched_at < end_utc)
        .filter(visible_content_clause())
        .order_by(*candidate_ordering(Content))
        .limit(HOURLY_DIGEST_CANDIDATE_LIMIT)
    )
    contents = result.scalars().all()

    items = [_digest_item_from_content(content) for content in contents]

    return HourlyDigestDetail(
        hour=hour,
        date=target_date.isoformat(),
        title=digest_row.title,
        summary=digest_row.summary,
        content_count=digest_row.content_count,
        sources=digest_row.sources or [],
        event_items=digest_row.items_json or [],
        items=items,
        generated_at=to_iso_z(digest_row.created_at),
    )
