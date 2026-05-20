"""Low-signal content cleanup HTTP routes.

The pure cleanup logic (``_build_low_signal_cleanup_report``,
``_junk_cleanup_reason``, ``_content_text_blob_for_junk_scan``) moved
to :mod:`app.domains.ingest.cleanup` in Phase 3 step 7 of the
module-refactor blueprint; this module keeps only the FastAPI route
handlers and re-imports the helpers (also re-exporting them so the
existing ``from app.interfaces.http.contents import _build_low_signal_cleanup_report``
chain — used by ``tests/test_content_quality_filters.py`` — keeps
resolving).
"""

from __future__ import annotations

from collections import Counter
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_async_db
from app.domains.ingest.cleanup import (  # noqa: F401 — re-exported as patch / import targets
    _build_low_signal_cleanup_report,
    _content_text_blob_for_junk_scan,
    _junk_cleanup_reason,
)
from app.models import Content

router = APIRouter()

__all__ = [
    "router",
    "_build_low_signal_cleanup_report",
    "_junk_cleanup_reason",
    "_content_text_blob_for_junk_scan",
]


@router.post("/cleanup-low-signal")
async def cleanup_low_signal_contents(
    apply: bool = Query(False, description="Delete matched contents when true"),
    source_id: Optional[UUID] = Query(None),
    preview_limit: int = Query(20, ge=1, le=200),
    max_delete: int = Query(2000, ge=1, le=50_000, description="Hard cap on rows deleted per apply"),
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
    capped = False
    if apply and matched:
        to_delete = matched[:max_delete]
        capped = len(matched) > len(to_delete)
        for content in to_delete:
            await db.delete(content)
        await db.commit()
        deleted_count = len(to_delete)

    return {
        "mode": "apply" if apply else "dry_run",
        "source_id": str(source_id) if source_id else None,
        "max_delete": max_delete,
        "delete_capped": capped,
        "scanned_count": len(contents),
        "matched_count": report["matched_count"],
        "deleted_count": deleted_count,
        "by_reason": report["by_reason"],
        "by_source": report["by_source"],
        "preview": report["preview"],
    }


@router.post("/cleanup-junk")
async def cleanup_junk_contents(
    apply: bool = Query(False, description="Delete matched rows when true"),
    source_id: Optional[UUID] = Query(None),
    preview_limit: int = Query(30, ge=1, le=500),
    max_delete: int = Query(2000, ge=1, le=50_000, description="Hard cap on rows deleted per apply"),
    match_embedded_binary: bool = Query(True, description="PNG/JPEG/GIF/WebP bytes mis-stored as text"),
    match_rss_thin_text: bool = Query(
        True,
        description="RSS rows where summary/full/translated summary are all shorter than threshold",
    ),
    rss_plain_min: int = Query(20, ge=1, le=500),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Remove obvious bad rows: binary garbage in text fields, and RSS items with almost no text
    (e.g. 36kr channel stubs). Dry-run by default; pass apply=true to delete.
    """
    if not match_embedded_binary and not match_rss_thin_text:
        raise HTTPException(
            status_code=422,
            detail="At least one of match_embedded_binary or match_rss_thin_text must be true",
        )

    query = select(Content).options(selectinload(Content.source))
    if source_id:
        query = query.filter(Content.source_id == source_id)

    result = await db.execute(query)
    contents = list(result.scalars().all())

    matched: list[Content] = []
    reason_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    preview_items: list[dict] = []

    for content in contents:
        reason = _junk_cleanup_reason(
            content,
            match_embedded_binary=match_embedded_binary,
            match_rss_thin_text=match_rss_thin_text,
            rss_plain_min=rss_plain_min,
        )
        if not reason:
            continue
        matched.append(content)
        reason_counts[reason] += 1
        src = content.source
        source_name = (src.name if src else None) or "-"
        source_counts[source_name] += 1
        if len(preview_items) < preview_limit:
            preview_items.append(
                {
                    "id": str(content.id),
                    "reason": reason,
                    "content_type": content.content_type,
                    "source_name": source_name,
                    "title": (content.title or "")[:120],
                    "url": (content.original_url or "")[:500],
                }
            )

    deleted_count = 0
    capped = False
    if apply and matched:
        to_delete = matched[:max_delete]
        capped = len(matched) > len(to_delete)
        for content in to_delete:
            await db.delete(content)
        await db.commit()
        deleted_count = len(to_delete)

    return {
        "mode": "apply" if apply else "dry_run",
        "source_id": str(source_id) if source_id else None,
        "max_delete": max_delete,
        "delete_capped": capped,
        "scanned_count": len(contents),
        "matched_count": len(matched),
        "deleted_count": deleted_count,
        "by_reason": dict(sorted(reason_counts.items())),
        "by_source": dict(source_counts.most_common()),
        "preview": preview_items,
        "flags": {
            "match_embedded_binary": match_embedded_binary,
            "match_rss_thin_text": match_rss_thin_text,
            "rss_plain_min": rss_plain_min,
        },
    }
