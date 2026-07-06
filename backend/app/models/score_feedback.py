"""User feedback on content scores (score lab)."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, JSON, String, Text
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
