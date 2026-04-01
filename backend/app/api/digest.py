"""API routes for digest generation."""

from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, extract
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_async_db
from app.models import Content, Source, HourlyDigest
from app.schemas.digest import (
    DigestResponse, DigestCategory, DigestItem,
    HourlyDigestSummary, HourlyDigestDetail,
)
from app.utils.datetime import to_iso_z, utcnow_naive
from app.utils.logger import get_logger

logger = get_logger(__name__)
SYSTEM_TZ = ZoneInfo("Asia/Shanghai")

router = APIRouter()


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


@router.get("", response_model=DigestResponse)
async def get_daily_digest(
    digest_date: Optional[str] = Query(None, alias="date"),
    category_ids: Optional[List[UUID]] = Query(None),
    keyword_ids: Optional[List[UUID]] = Query(None),
    unread_only: bool = True,
    source_types: Optional[List[str]] = Query(None),
    db: AsyncSession = Depends(get_async_db)
):
    """Get daily digest for a specific date."""
    # Default to today
    if digest_date:
        target_date = datetime.strptime(digest_date, "%Y-%m-%d").date()
    else:
        target_date = date.today()
    
    # Convert local date to UTC range to leverage ix_content_fetched_at index
    day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=SYSTEM_TZ).astimezone(timezone.utc).replace(tzinfo=None)
    day_end = day_start + timedelta(days=1)

    # Build query
    query = (
        select(Content)
        .options(selectinload(Content.source))
        .filter(Content.fetched_at >= day_start, Content.fetched_at < day_end)
    )
    
    # Apply filters
    if category_ids:
        query = query.join(Source).filter(Source.category_id.in_(category_ids))
    
    if unread_only:
        query = query.filter(Content.read_status == False)
    
    if source_types:
        query = query.filter(Content.content_type.in_(source_types))
    
    # Note: keyword_ids filtering would require JSON query which is complex
    # For now, we filter after fetching
    
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
    digest = DigestResponse(
        date=target_date.isoformat(),
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
        
        item = DigestItem(
            id=content.id,
            source_name=content.source.name if content.source else "Unknown",
            title=content.title,
            translated_title=content.translated_title,
            summary=content.summary,
            translated_summary=content.translated_summary,
            url=content.original_url,
            publish_time=content.publish_time,
            fetched_at=content.fetched_at,
            read_status=content.read_status,
            favorited=content.favorited,
            keyword_matches=content.keyword_matches or [],
            metadata=content.metadata_ or {}
        )
        
        digest.categories[category_key].items.append(item)
        digest.categories[category_key].count += 1
    
    return digest


@router.get("/stats")
async def get_digest_stats(
    days: int = Query(7, ge=1, le=30),
    db: AsyncSession = Depends(get_async_db)
):
    """Get digest statistics for the past N days."""
    from datetime import timedelta
    
    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)

    # Convert local date range to UTC bounds for index-friendly filtering
    stats_start_utc = datetime(start_date.year, start_date.month, start_date.day, tzinfo=SYSTEM_TZ).astimezone(timezone.utc).replace(tzinfo=None)
    stats_end_utc = datetime(end_date.year, end_date.month, end_date.day, tzinfo=SYSTEM_TZ).astimezone(timezone.utc).replace(tzinfo=None) + timedelta(days=1)

    # Get content counts per day
    result = await db.execute(
        select(
            func.date(Content.fetched_at).label("date"),
            func.count(Content.id).label("count")
        )
        .filter(Content.fetched_at >= stats_start_utc, Content.fetched_at < stats_end_utc)
        .group_by(func.date(Content.fetched_at))
        .order_by(func.date(Content.fetched_at))
    )
    daily_counts = result.all()

    # Get counts by content type
    result = await db.execute(
        select(
            Content.content_type,
            func.count(Content.id).label("count")
        )
        .filter(Content.fetched_at >= stats_start_utc, Content.fetched_at < stats_end_utc)
        .group_by(Content.content_type)
    )
    type_counts = result.all()
    
    # Get unread count
    result = await db.execute(
        select(func.count(Content.id))
        .filter(Content.read_status == False)
    )
    unread_count = result.scalar()
    
    # Get favorited count
    result = await db.execute(
        select(func.count(Content.id))
        .filter(Content.favorited == True)
    )
    favorited_count = result.scalar()
    
    return {
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "days": days
        },
        "daily_counts": [
            {"date": row.date.isoformat(), "count": row.count}
            for row in daily_counts
        ],
        "type_counts": {row.content_type: row.count for row in type_counts},
        "unread_count": unread_count,
        "favorited_count": favorited_count
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


def _completed_hour_label_to_utc_window(target_date: date, hour: int) -> tuple[datetime, datetime]:
    """Map a digest label hour to the completed local-hour window it summarizes."""
    end_local = datetime(target_date.year, target_date.month, target_date.day, hour, tzinfo=SYSTEM_TZ)
    start_local = end_local - timedelta(hours=1)
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
        target_date = date.today()
    
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
        target_date = date.today()
    
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
            items=[],
            generated_at=to_iso_z(utcnow_naive()),
        )

    start_utc, end_utc = _completed_hour_label_to_utc_window(target_date, hour)
    result = await db.execute(
        select(Content)
        .options(selectinload(Content.source))
        .filter(Content.content_type == "website")
        .filter(Content.fetched_at >= start_utc)
        .filter(Content.fetched_at < end_utc)
        .order_by(Content.publish_time.desc().nulls_last(), Content.fetched_at.desc())
    )
    contents = result.scalars().all()

    items = []
    for content in contents:
        items.append(DigestItem(
            id=content.id,
            source_name=content.source.name if content.source else "Unknown",
            title=content.title,
            translated_title=content.translated_title,
            summary=content.summary,
            translated_summary=content.translated_summary,
            url=content.original_url,
            publish_time=content.publish_time,
            fetched_at=content.fetched_at,
            read_status=content.read_status,
            favorited=content.favorited,
            keyword_matches=content.keyword_matches or [],
            metadata=content.metadata_ or {},
        ))

    return HourlyDigestDetail(
        hour=hour,
        date=target_date.isoformat(),
        title=digest_row.title,
        summary=digest_row.summary,
        content_count=digest_row.content_count,
        sources=digest_row.sources or [],
        items=items,
        generated_at=to_iso_z(digest_row.created_at),
    )
