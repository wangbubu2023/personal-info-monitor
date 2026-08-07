"""Normalized Source state inspection and compatibility backfill endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.domains.sources.state_service import ensure_source_state_async
from app.models import Source, SourceDiscoveryStats, SourceFetchState, SourcePolicy, SourceSessionState

router = APIRouter()


@router.get("/{source_id}/state")  # noqa: V103
async def get_source_state(source_id: UUID, db: AsyncSession = Depends(get_async_db)):  # noqa: V103
    source_result = await db.execute(select(Source).filter(Source.id == source_id))
    source = source_result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    await ensure_source_state_async(db, source)
    await db.commit()
    rows: dict[str, object] = {}
    for key, model in (
        ("fetch", SourceFetchState),
        ("discovery", SourceDiscoveryStats),
        ("session", SourceSessionState),
        ("policy", SourcePolicy),
    ):
        result = await db.execute(select(model).filter(model.source_id == source_id))
        row = result.scalar_one_or_none()
        if row is None:
            rows[key] = None
            continue
        rows[key] = {
            column.name: getattr(row, column.name)
            for column in model.__table__.columns
            if column.name not in {"id", "source_id"}
        }
    return {"source_id": str(source_id), "state": rows}


@router.post("/state/backfill")  # noqa: V103
async def backfill_source_state(db: AsyncSession = Depends(get_async_db)):  # noqa: V103
    result = await db.execute(select(Source).order_by(Source.created_at.asc()))
    sources = list(result.scalars().all())
    for source in sources:
        await ensure_source_state_async(db, source)
    await db.commit()
    return {"status": "ok", "backfilled": len(sources)}
