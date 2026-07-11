"""API routes for dashboard summaries."""

from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models import Content, Source
from app.utils.datetime import user_timezone
from app.utils.ttl_cache import TTLCache

router = APIRouter()
_dashboard_cache = TTLCache(ttl_seconds=30)


def _today_window_utc_naive() -> tuple[datetime, datetime]:
    """Return [today_start, tomorrow_start) in UTC-naive for DB comparison."""
    tz = user_timezone()
    now_local = datetime.now(tz)
    start_local = datetime.combine(now_local.date(), time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


@router.get("/stats")
async def dashboard_stats(db: AsyncSession = Depends(get_async_db)):
    """Get dashboard statistics."""
    cache_key = "dashboard:stats"
    cached = _dashboard_cache.get(cache_key)
    if cached is not None:
        return cached

    start_utc, end_utc = _today_window_utc_naive()
    today_result = await db.execute(
        select(func.count(Content.id)).filter(
            Content.fetched_at >= start_utc,
            Content.fetched_at < end_utc,
        )
    )
    today_total = today_result.scalar()

    unread_result = await db.execute(
        select(func.count(Content.id)).filter(Content.read_status == False)
    )
    unread_count = unread_result.scalar()

    sources_result = await db.execute(
        select(func.count(Source.id)).filter(Source.enabled == True)
    )
    active_sources = sources_result.scalar()

    favorited_result = await db.execute(
        select(func.count(Content.id)).filter(Content.favorited == True)
    )
    favorited_count = favorited_result.scalar()

    payload = {
        "today_total": today_total,
        "unread_count": unread_count,
        "active_sources": active_sources,
        "favorited_count": favorited_count,
    }
    return _dashboard_cache.set(cache_key, payload)
