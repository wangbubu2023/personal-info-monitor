"""Daily and weekly content digest generation."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Content, Source
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SYSTEM_TZ = ZoneInfo("Asia/Shanghai")


class DigestService:
    """Generate content digests from stored content rows."""

    def __init__(self, db: Session):
        self.db = db

    def generate_daily_digest(
        self,
        date: date,
        keyword_ids: Optional[List[UUID]] = None,
        unread_only: bool = True,
        source_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Generate a daily digest."""
        logger.info("Generating digest for %s", date)

        day_start = (
            datetime(date.year, date.month, date.day, tzinfo=_SYSTEM_TZ)
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )
        day_end = day_start + timedelta(days=1)

        query = (
            self.db.query(Content)
            .join(Source)
            .filter(Content.fetched_at >= day_start, Content.fetched_at < day_end)
        )

        if unread_only:
            query = query.filter(Content.read_status == False)  # noqa: E712

        if source_types:
            query = query.filter(Content.content_type.in_(source_types))

        contents = query.order_by(Content.publish_time.desc()).all()

        if keyword_ids:
            keyword_id_strs = [str(kid) for kid in keyword_ids]
            filtered = []
            for content in contents:
                if not content.keyword_matches:
                    continue
                for match in content.keyword_matches:
                    if match.get("id") in keyword_id_strs:
                        filtered.append(content)
                        break
            contents = filtered

        digest = {
            "date": date.isoformat(),
            "total_items": len(contents),
            "categories": {
                "websites": {"count": 0, "items": []},
                "rss": {"count": 0, "items": []},
                "x_accounts": {"count": 0, "items": []},
                "youtube": {"count": 0, "items": []},
                "podcasts": {"count": 0, "items": []},
            },
        }

        for content in contents:
            category_key = self._get_category_key(content.content_type)
            item = self._format_content_item(content)

            digest["categories"][category_key]["items"].append(item)
            digest["categories"][category_key]["count"] += 1

        return digest

    def _get_category_key(self, content_type: str) -> str:
        """Map content type to category key."""
        mapping = {
            "website": "websites",
            "rss": "rss",
            "x": "x_accounts",
            "youtube": "youtube",
            "podcast": "podcasts",
        }
        return mapping.get(content_type, "websites")

    def _format_content_item(self, content: Content) -> Dict[str, Any]:
        """Format a content item for digest."""
        return {
            "id": str(content.id),
            "source_id": str(content.source_id),
            "source_name": content.source.name if content.source else "Unknown",
            "title": content.title,
            "translated_title": content.translated_title,
            "summary": content.summary,
            "translated_summary": content.translated_summary,
            "url": content.original_url,
            "publish_time": content.publish_time.isoformat() if content.publish_time else None,
            "read_status": content.read_status,
            "favorited": content.favorited,
            "keyword_matches": content.keyword_matches or [],
        }

    def get_weekly_summary(self, end_date: Optional[date] = None) -> Dict[str, Any]:
        """Generate a weekly summary."""
        if end_date is None:
            end_date = date.today()

        start_date = end_date - timedelta(days=6)
        week_start_utc = (
            datetime(start_date.year, start_date.month, start_date.day, tzinfo=_SYSTEM_TZ)
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )
        week_end_utc = (
            datetime(end_date.year, end_date.month, end_date.day, tzinfo=_SYSTEM_TZ)
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
            + timedelta(days=1)
        )

        daily_counts = {}
        type_counts = {"website": 0, "x": 0, "youtube": 0, "podcast": 0}

        current_date = start_date
        while current_date <= end_date:
            day_start = (
                datetime(current_date.year, current_date.month, current_date.day, tzinfo=_SYSTEM_TZ)
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )
            day_end = day_start + timedelta(days=1)
            count = self.db.query(Content).filter(Content.fetched_at >= day_start, Content.fetched_at < day_end).count()
            daily_counts[current_date.isoformat()] = count
            current_date += timedelta(days=1)

        for content_type in type_counts:
            count = (
                self.db.query(Content)
                .filter(
                    Content.content_type == content_type,
                    Content.fetched_at >= week_start_utc,
                    Content.fetched_at < week_end_utc,
                )
                .count()
            )
            type_counts[content_type] = count

        top_sources = (
            self.db.query(Source.name, func.count(Content.id).label("count"))
            .join(Content)
            .filter(
                Content.fetched_at >= week_start_utc,
                Content.fetched_at < week_end_utc,
            )
            .group_by(Source.id)
            .order_by(func.count(Content.id).desc())
            .limit(10)
            .all()
        )

        return {
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "total_items": sum(daily_counts.values()),
            "daily_counts": daily_counts,
            "type_counts": type_counts,
            "top_sources": [{"name": s.name, "count": s.count} for s in top_sources],
        }


__all__ = ["DigestService"]
