"""Score lab API — explain scores and collect calibration feedback."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_async_db
from app.domains.score.score_explain import explain_content_row
from app.features import KEYWORD_MONITORING_ENABLED
from app.models import Content, Keyword, ScoreFeedback
from app.schemas.score_lab import (
    ScoreExplainResponse,
    ScoreFeedbackCreate,
    ScoreFeedbackItem,
    ScoreFeedbackListResponse,
    ScoreLabContentListResponse,
    ScoreLabContentSummary,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

SCORE_LAB_POOL_SIZE = 50

_VALID_DIRECTIONS = frozenset({"too_high", "too_low", "ok"})
_VALID_EXPECTED = frozenset({"selected", "candidate", "rejected"})


def _meta_get(meta: dict[str, Any] | None, key: str) -> Any:
    if not isinstance(meta, dict):
        return None
    return meta.get(key)


def _serialize_lab_item(content: Content) -> ScoreLabContentSummary:
    meta = content.metadata_ if isinstance(content.metadata_, dict) else {}
    source = content.source
    score_raw = _meta_get(meta, "article_score",) or _meta_get(meta, "final_score")
    try:
        article_score = float(score_raw) if score_raw is not None else None
    except (TypeError, ValueError):
        article_score = None
    return ScoreLabContentSummary(
        id=content.id,
        title=content.title or "",
        source_name=source.name if source else None,
        content_type=content.content_type or "",
        original_url=content.original_url or "",
        publish_time=content.publish_time,
        fetched_at=content.fetched_at,
        article_score=article_score,
        selection_status=_meta_get(meta, "selection_status"),
        lane=_meta_get(meta, "lane"),
        fetch_acceptance=_meta_get(meta, "fetch_acceptance"),
    )


@router.get("/contents", response_model=ScoreLabContentListResponse)
async def list_scored_contents(
    selection_status: Optional[str] = None,
    lane: Optional[str] = None,
    min_score: Optional[float] = None,
    max_score: Optional[float] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db),
):
    """List the latest scored contents for the score lab (fixed pool, score-sorted)."""

    query = select(Content).options(selectinload(Content.source))

    if selection_status:
        clause = text("json_extract(contents.metadata, '$.selection_status') = :selection_status")
        query = query.where(clause.bindparams(selection_status=selection_status))
    if lane:
        clause = text("json_extract(contents.metadata, '$.lane') = :lane")
        query = query.where(clause.bindparams(lane=lane))
    if min_score is not None:
        clause = text("CAST(json_extract(contents.metadata, '$.article_score') AS REAL) >= :min_score")
        query = query.where(clause.bindparams(min_score=min_score))
    if max_score is not None:
        clause = text("CAST(json_extract(contents.metadata, '$.article_score') AS REAL) <= :max_score")
        query = query.where(clause.bindparams(max_score=max_score))
    if search and search.strip():
        safe = search.strip()[:120].replace("%", "").replace("_", "")
        pat = f"%{safe}%"
        query = query.where(Content.title.ilike(pat))

    rows = (
        await db.execute(
            query.order_by(Content.fetched_at.desc()).limit(SCORE_LAB_POOL_SIZE)
        )
    ).scalars().all()

    def _article_score(content: Content) -> float:
        meta = content.metadata_ if isinstance(content.metadata_, dict) else {}
        raw = meta.get("article_score", meta.get("final_score"))
        try:
            return float(raw)
        except (TypeError, ValueError):
            return -1.0

    rows.sort(key=_article_score, reverse=True)

    return ScoreLabContentListResponse(
        items=[_serialize_lab_item(row) for row in rows],
        total=len(rows),
        page=1,
        page_size=SCORE_LAB_POOL_SIZE,
    )


@router.get("/contents/{content_id}/explain", response_model=ScoreExplainResponse)
async def explain_content(
    content_id: UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """Recompute and explain the score for one content row."""
    content = (
        await db.execute(
            select(Content).options(selectinload(Content.source)).where(Content.id == str(content_id))
        )
    ).scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    keyword_rows: list = []
    if KEYWORD_MONITORING_ENABLED:
        keyword_rows = (await db.execute(select(Keyword).where(Keyword.enabled == True))).scalars().all()  # noqa: E712

    payload = explain_content_row(content, keyword_objects=keyword_rows)
    return ScoreExplainResponse(explain=payload)


@router.post("/feedback", response_model=ScoreFeedbackItem)
async def create_score_feedback(
    body: ScoreFeedbackCreate,
    db: AsyncSession = Depends(get_async_db),
):
    if body.direction not in _VALID_DIRECTIONS:
        raise HTTPException(status_code=400, detail="Invalid direction")
    if body.expected_status and body.expected_status not in _VALID_EXPECTED:
        raise HTTPException(status_code=400, detail="Invalid expected_status")

    content = (
        await db.execute(select(Content).where(Content.id == str(body.content_id)))
    ).scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    keyword_rows: list = []
    if KEYWORD_MONITORING_ENABLED:
        keyword_rows = (await db.execute(select(Keyword).where(Keyword.enabled == True))).scalars().all()  # noqa: E712

    explain = explain_content_row(content, keyword_objects=keyword_rows)
    snapshot = {
        "article_score": explain.get("recomputed", {}).get("article_score"),
        "selection_status": explain.get("recomputed", {}).get("selection_status"),
        "dimension_scores": explain.get("dimension_scores"),
        "lane": explain.get("lane"),
        "impact_cap_scope": explain.get("impact_cap_scope"),
        "stored_article_score": explain.get("stored", {}).get("article_score"),
        "score_delta": explain.get("score_delta"),
    }

    row = ScoreFeedback(
        content_id=str(body.content_id),
        direction=body.direction,
        expected_status=body.expected_status,
        note=(body.note or "").strip() or None,
        snapshot=snapshot,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    logger.info("Score feedback recorded for %s: %s", body.content_id, body.direction)
    return ScoreFeedbackItem(
        id=row.id,
        content_id=row.content_id,
        direction=row.direction,
        expected_status=row.expected_status,
        note=row.note,
        snapshot=row.snapshot or {},
        created_at=row.created_at,
        content_title=content.title,
    )


@router.get("/feedback", response_model=ScoreFeedbackListResponse)
async def list_score_feedback(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
):
    rows = (
        await db.execute(
            select(ScoreFeedback, Content.title)
            .join(Content, Content.id == ScoreFeedback.content_id)
            .order_by(ScoreFeedback.created_at.desc())
            .limit(limit)
        )
    ).all()

    items = [
        ScoreFeedbackItem(
            id=feedback.id,
            content_id=feedback.content_id,
            direction=feedback.direction,
            expected_status=feedback.expected_status,
            note=feedback.note,
            snapshot=feedback.snapshot or {},
            created_at=feedback.created_at,
            content_title=title,
        )
        for feedback, title in rows
    ]
    total = (await db.execute(select(func.count(ScoreFeedback.id)))).scalar() or 0
    return ScoreFeedbackListResponse(items=items, total=int(total))
