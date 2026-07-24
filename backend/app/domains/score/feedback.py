"""Feedback event recording for score calibration and user interactions."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.models import Content, QualityAdjudication, ScoreFeedback

SCORE_CALIBRATION_EVENT = "score_calibration"
USER_INTERACTION_EVENTS = frozenset({"open", "star", "hide"})
EVENT_CLUSTER_FEEDBACK_EVENTS = frozenset(
    {
        "event_wrong_merge",
        "event_missing_merge",
        "event_wrong_title",
        "event_wrong_fact",
        "event_wrong_source_role",
    }
)
VALID_FEEDBACK_EVENT_TYPES = frozenset({SCORE_CALIBRATION_EVENT, *USER_INTERACTION_EVENTS, *EVENT_CLUSTER_FEEDBACK_EVENTS})


def content_feedback_snapshot(content: Content, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = content.metadata_ if isinstance(content.metadata_, dict) else {}
    snapshot: dict[str, Any] = {
        "article_score": meta.get("article_score", meta.get("final_score")),
        "selection_status": meta.get("selection_status"),
        "lane": meta.get("lane"),
        "source_id": str(content.source_id) if content.source_id else None,
        "content_type": content.content_type,
        "read_status": bool(content.read_status),
        "favorited": bool(content.favorited),
        "archived": bool(content.archived),
    }
    if extra:
        snapshot.update(extra)
    return snapshot


async def record_score_feedback_event(
    db: AsyncSession,
    content: Content,
    *,
    event_type: str,
    event_value: Any = None,
    direction: str | None = None,
    expected_status: str | None = None,
    note: str | None = None,
    snapshot: dict[str, Any] | None = None,
) -> ScoreFeedback:
    if event_type not in VALID_FEEDBACK_EVENT_TYPES:
        raise ValueError(f"invalid feedback event_type: {event_type}")

    row = ScoreFeedback(
        content_id=str(content.id),
        direction=direction or event_type,
        expected_status=expected_status,
        note=(note or "").strip() or None,
        event_type=event_type,
        event_value=event_value,
        snapshot=snapshot or content_feedback_snapshot(content),
    )
    db.add(row)
    return row


async def adjudicate_quality_feedback(
    db: AsyncSession,
    feedback_id: str,
    *,
    verdict: str,
    adjudicator: str,
    rationale: str,
    evidence: dict[str, Any] | None = None,
) -> QualityAdjudication:
    """Confirm/reject one observation without changing generic content scores."""

    if verdict not in {"confirmed", "rejected"}:
        raise ValueError("verdict must be confirmed or rejected")
    feedback = await db.scalar(select(ScoreFeedback).where(ScoreFeedback.id == feedback_id))
    if feedback is None:
        raise LookupError("feedback observation not found")
    issue_type = str(feedback.event_type or "")
    if issue_type not in EVENT_CLUSTER_FEEDBACK_EVENTS:
        raise ValueError("only explicit quality observations can be adjudicated")
    existing = await db.scalar(select(QualityAdjudication).where(QualityAdjudication.feedback_id == feedback_id))
    if existing is not None:
        raise ValueError("feedback observation is already adjudicated")
    reviewer = adjudicator.strip()
    reason = rationale.strip()
    if not reviewer or not reason:
        raise ValueError("adjudicator and rationale are required")
    confirmed = verdict == "confirmed"
    row = QualityAdjudication(
        feedback_id=feedback_id,
        issue_type=issue_type,
        status="adjudicated",
        verdict=verdict,
        adjudicator=reviewer,
        rationale=reason,
        gold_candidate=confirmed,
        hard_negative=confirmed and issue_type == "event_wrong_merge",
        evidence=evidence or {},
    )
    db.add(row)
    return row


__all__ = [
    "SCORE_CALIBRATION_EVENT",
    "USER_INTERACTION_EVENTS",
    "EVENT_CLUSTER_FEEDBACK_EVENTS",
    "VALID_FEEDBACK_EVENT_TYPES",
    "adjudicate_quality_feedback",
    "content_feedback_snapshot",
    "record_score_feedback_event",
]
