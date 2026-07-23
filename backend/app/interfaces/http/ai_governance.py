"""Operator APIs for M1A subjective-scoring governance."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.domains.score.score_subjective import (
    SUBJECTIVE_PROMPT_VERSION,
    subjective_metrics_snapshot,
)
from app.models.ai_governance import AiSubjectiveScoreCache
from app.models.content import Content

router = APIRouter()


@router.get("/subjective-scoring/metrics")
async def get_subjective_scoring_metrics(db: AsyncSession = Depends(get_async_db)):
    totals = (
        await db.execute(
            select(
                func.count(AiSubjectiveScoreCache.id),
                func.coalesce(func.sum(AiSubjectiveScoreCache.hit_count), 0),
                func.coalesce(func.sum(AiSubjectiveScoreCache.token_estimate), 0),
                func.coalesce(func.sum(AiSubjectiveScoreCache.estimated_cost), 0.0),
            )
        )
    ).one()
    by_state_rows = (
        await db.execute(
            select(AiSubjectiveScoreCache.state, func.count(AiSubjectiveScoreCache.id))
            .group_by(AiSubjectiveScoreCache.state)
        )
    ).all()
    return {
        "schema_version": 1,
        "process": subjective_metrics_snapshot(),
        "persistent": {
            "cache_entries": int(totals[0] or 0),
            "cache_hits": int(totals[1] or 0),
            "token_estimate": int(totals[2] or 0),
            "estimated_cost": float(totals[3] or 0.0),
            "states": {str(state): int(count) for state, count in by_state_rows},
        },
        "prompt_version": SUBJECTIVE_PROMPT_VERSION,
        "shadow_weight": 0.0,
    }


@router.get("/subjective-scoring/cache/{content_id}")
async def get_subjective_scoring_cache(
    content_id: str,
    db: AsyncSession = Depends(get_async_db),
):
    rows = (
        await db.execute(
            select(AiSubjectiveScoreCache)
            .filter(AiSubjectiveScoreCache.content_id == content_id)
            .order_by(AiSubjectiveScoreCache.created_at.desc())
        )
    ).scalars().all()
    return {
        "content_id": content_id,
        "versions": [
            {
                "cache_key": row.cache_key,
                "input_hash": row.input_hash,
                "input_scope": row.input_scope,
                "provider": row.provider,
                "model": row.model,
                "model_version": row.model_version,
                "prompt_version": row.prompt_version,
                "score": row.score,
                "rationale": row.rationale,
                "token_estimate": row.token_estimate,
                "actual_usage": row.actual_usage,
                "estimated_cost": row.estimated_cost,
                "state": row.state,
                "failure_code": row.failure_code,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "last_hit_at": row.last_hit_at.isoformat() if row.last_hit_at else None,
                "hit_count": row.hit_count,
            }
            for row in rows
        ],
    }


@router.post("/subjective-scoring/reprocess")
async def reprocess_subjective_scoring(
    payload: dict,
    db: AsyncSession = Depends(get_async_db),
):
    """Explicit, bounded, dry-run-first backfill surface."""

    content_ids = list(dict.fromkeys(str(value).strip() for value in payload.get("content_ids", []) if str(value).strip()))
    if not content_ids:
        raise HTTPException(status_code=422, detail="content_ids scope is required")
    if len(content_ids) > 100:
        raise HTTPException(status_code=422, detail="content_ids scope is limited to 100")
    dry_run = payload.get("dry_run", True) is not False
    existing = set(
        (
            await db.execute(select(Content.id).filter(Content.id.in_(content_ids)))
        ).scalars().all()
    )
    selected = [content_id for content_id in content_ids if content_id in existing]
    response = {
        "dry_run": dry_run,
        "requested": len(content_ids),
        "matched": len(selected),
        "missing": [content_id for content_id in content_ids if content_id not in existing],
        "prompt_version": SUBJECTIVE_PROMPT_VERSION,
        "idempotency_version": f"subjective:{SUBJECTIVE_PROMPT_VERSION}",
    }
    if dry_run:
        return {**response, "enqueued": 0}

    from app.tasks.task_queue import task_queue

    enqueued = 0
    for content_id in selected:
        accepted = await task_queue.enqueue_ingest_finish(
            content_id,
            job_id=f"finish:subjective-{SUBJECTIVE_PROMPT_VERSION}",
        )
        enqueued += int(bool(accepted))
    return {**response, "enqueued": enqueued}
