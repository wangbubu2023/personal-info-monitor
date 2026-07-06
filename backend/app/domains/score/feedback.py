"""Feedback event recording for score calibration and user interactions."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Content, ScoreFeedback

SCORE_CALIBRATION_EVENT = "score_calibration"
USER_INTERACTION_EVENTS = frozenset({"open", "star", "hide"})
VALID_FEEDBACK_EVENT_TYPES = frozenset({SCORE_CALIBRATION_EVENT, *USER_INTERACTION_EVENTS})


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


__all__ = [
    "SCORE_CALIBRATION_EVENT",
    "USER_INTERACTION_EVENTS",
    "VALID_FEEDBACK_EVENT_TYPES",
    "content_feedback_snapshot",
    "record_score_feedback_event",
]
