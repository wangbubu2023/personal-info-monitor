"""User feedback observations and their explicit quality adjudications."""

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class ScoreFeedback(Base):
    """Single-user score calibration feedback."""

    __tablename__ = "score_feedback"
    __table_args__ = (
        Index("ix_score_feedback_event_type", "event_type"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    content_id = Column(UUIDString, ForeignKey("contents.id", ondelete="CASCADE"), nullable=False, index=True)
    direction = Column(String(16), nullable=False)  # too_high | too_low | ok
    expected_status = Column(String(16), nullable=True)
    note = Column(Text, nullable=True)
    event_type = Column(String(32), nullable=True)
    event_value = Column(JSON, nullable=True)
    snapshot = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False, index=True)

    content = relationship("Content")


class QualityAdjudication(Base):
    """Immutable human verdict over a quality-feedback observation."""

    __tablename__ = "quality_adjudications"
    __table_args__ = (
        UniqueConstraint("feedback_id", name="uq_quality_adjudication_feedback"),
        Index("ix_quality_adjudications_issue_status", "issue_type", "status"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    feedback_id = Column(
        UUIDString,
        ForeignKey("score_feedback.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    issue_type = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default="adjudicated")
    verdict = Column(String(24), nullable=False)
    adjudicator = Column(String(128), nullable=False)
    rationale = Column(Text, nullable=False)
    gold_candidate = Column(Boolean, nullable=False, default=False)
    hard_negative = Column(Boolean, nullable=False, default=False)
    evidence = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False, index=True)

    feedback = relationship("ScoreFeedback")
