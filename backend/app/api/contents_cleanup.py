"""Low-signal content cleanup routes and helpers."""

from __future__ import annotations

from collections import Counter
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_async_db
from app.models import Content
from app.pipeline.utils import get_website_content_reject_reason

router = APIRouter()


def _build_low_signal_cleanup_report(
    contents: list[Content],
    *,
    preview_limit: int,
) -> tuple[list[Content], dict]:
    matched: list[Content] = []
    reason_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    preview_items: list[dict] = []

    for content in contents:
        source = content.source
        if not source:
            continue
        reason = get_website_content_reject_reason(
            source.url,
            {
                "title": content.title,
                "content": content.full_content or content.summary or "",
                "url": content.original_url,
                "html": "",
            },
        )
        if not reason:
            continue

        matched.append(content)
        source_name = source.name or "-"
        reason_counts[reason] += 1
        source_counts[source_name] += 1

        if len(preview_items) < preview_limit:
            preview_items.append(
                {
                    "id": str(content.id),
                    "reason": reason,
                    "source_id": str(source.id),
                    "source_name": source_name,
                    "title": content.title,
                    "url": content.original_url,
                    "favorited": content.favorited,
                    "archived": content.archived,
                    "read_status": content.read_status,
                    "publish_time": content.publish_time.isoformat() if content.publish_time else None,
                }
            )

    report = {
        "matched_count": len(matched),
        "by_reason": dict(sorted(reason_counts.items())),
        "by_source": dict(source_counts.most_common()),
        "preview": preview_items,
    }
    return matched, report


@router.post("/cleanup-low-signal")
async def cleanup_low_signal_contents(
    apply: bool = Query(False, description="Delete matched contents when true"),
    source_id: Optional[UUID] = Query(None),
    preview_limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
):
    """Dry-run or delete obvious historical low-signal website contents."""
    query = (
        select(Content)
        .options(selectinload(Content.source))
        .filter(Content.content_type == "website")
    )
    if source_id:
        query = query.filter(Content.source_id == source_id)

    result = await db.execute(query)
    contents = list(result.scalars().all())
    matched, report = _build_low_signal_cleanup_report(contents, preview_limit=preview_limit)

    deleted_count = 0
    if apply and matched:
        for content in matched:
            await db.delete(content)
        await db.commit()
        deleted_count = len(matched)

    return {
        "mode": "apply" if apply else "dry_run",
        "source_id": str(source_id) if source_id else None,
        "scanned_count": len(contents),
        "matched_count": report["matched_count"],
        "deleted_count": deleted_count,
        "by_reason": report["by_reason"],
        "by_source": report["by_source"],
        "preview": report["preview"],
    }
