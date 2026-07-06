"""Source dry-run diagnostics.

Runs the fetch pipeline through collect -> normalize -> build, then rolls back
the session instead of storing content or dispatching finish jobs.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models import Content, Source
from ._helpers import _source_is_visible

router = APIRouter()


def _sample_raw(item: dict[str, Any]) -> dict[str, Any]:
    body = item.get("content") or item.get("summary") or ""
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "title": item.get("title"),
        "url": item.get("url"),
        "external_id": item.get("external_id"),
        "publish_time": str(item.get("publish_time")) if item.get("publish_time") else None,
        "body_chars": len(str(body).strip()),
        "metadata_keys": sorted(str(k) for k in metadata.keys())[:20],
    }


def _sample_content(content: Content) -> dict[str, Any]:
    metadata = content.metadata_ if isinstance(content.metadata_, dict) else {}
    return {
        "title": content.title,
        "url": content.original_url,
        "external_id": content.external_id,
        "publish_time": content.publish_time.isoformat() if content.publish_time else None,
        "full_content_chars": len((content.full_content or "").strip()),
        "summary_chars": len((content.summary or "").strip()),
        "metadata_keys": sorted(str(k) for k in metadata.keys())[:20],
    }


def _skip_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for item in items:
        reason = str(item.get("reason") or "unknown")
        summary[reason] = summary.get(reason, 0) + 1
    return summary


async def run_source_dry_run(source_id: UUID, *, sample_limit: int = 5) -> dict[str, Any]:
    from app.database import SessionLocal
    from app.domains.ingest.build_content import build_raw_content_objects
    from app.domains.ingest.normalizer import NormalizerStage
    from app.domains.fetch.collector_stage import CollectorStage

    db = SessionLocal()
    try:
        source = db.query(Source).filter(Source.id == str(source_id)).first()
        if not source or not _source_is_visible(source):
            raise HTTPException(status_code=404, detail="Source not found")

        raw_contents, merged_warning, primary_warning = await CollectorStage.execute(db, source)
        normalizer_skips: list[dict[str, Any]] = []
        valid_raw_contents, stale_skipped = await NormalizerStage.execute(
            db,
            source,
            raw_contents,
            manual_trigger=True,
            diagnostics=normalizer_skips,
        )
        content_objects, build_failed = await build_raw_content_objects(valid_raw_contents, source)
        normalized_skipped = max(0, len(raw_contents) - len(valid_raw_contents) - int(stale_skipped or 0))

        return {
            "source_id": str(source.id),
            "source_name": source.name,
            "source_type": source.type.value if hasattr(source.type, "value") else str(source.type),
            "dry_run": True,
            "would_write": False,
            "warnings": {
                "merged": merged_warning,
                "primary": {
                    "code": primary_warning[0],
                    "severity": primary_warning[1],
                    "message": primary_warning[2],
                } if primary_warning else None,
            },
            "stages": {
                "collector": {"count": len(raw_contents)},
                "normalizer": {
                    "input_count": len(raw_contents),
                    "valid_count": len(valid_raw_contents),
                    "stale_skipped": stale_skipped,
                    "other_skipped": normalized_skipped,
                },
                "builder": {
                    "would_store_count": len(content_objects),
                    "build_failed": build_failed,
                },
            },
            "samples": {
                "raw": [_sample_raw(item) for item in raw_contents[:sample_limit]],
                "would_store": [_sample_content(item) for item in content_objects[:sample_limit]],
            },
            "diagnostics": {
                "normalizer_skip_summary": _skip_summary(normalizer_skips),
                "normalizer_skips": normalizer_skips[:sample_limit],
            },
            "runtime": {
                "fetch_diag": getattr(source, "_runtime_fetch_diag", None),
                "metadata_preview": {
                    key: value
                    for key, value in (source.metadata_ if isinstance(source.metadata_, dict) else {}).items()
                    if key in {"rss_url", "rss_urls", "session_health", "discovery_diagnostics"}
                },
            },
        }
    finally:
        db.rollback()
        db.close()


@router.post("/{source_id}/dry-run")
async def dry_run_source(
    source_id: UUID,
    sample_limit: int = Query(5, ge=0, le=20),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(Source.id).filter(Source.id == source_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return await run_source_dry_run(source_id, sample_limit=sample_limit)
