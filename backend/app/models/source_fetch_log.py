"""Per-fetch source attempt log."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class SourceFetchLog(Base):
    """One fetch attempt outcome for source-level health analytics."""

    __tablename__ = "source_fetch_log"
    __table_args__ = (
        Index("ix_source_fetch_log_source_attempted", "source_id", "attempted_at"),
        Index("ix_source_fetch_log_outcome", "outcome"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id = Column(UUIDString, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    attempted_at = Column(DateTime, default=utcnow_naive, nullable=False, index=True)
    outcome = Column(String(16), nullable=False)
    severity = Column(String(16), nullable=True)
    failure_code = Column(String(64), nullable=True)
    saved_count = Column(Integer, nullable=False, default=0)
    latency_ms = Column(Integer, nullable=True)
    fulltext_ok = Column(Integer, nullable=False, default=0)
    fulltext_total = Column(Integer, nullable=False, default=0)
    preferred_strategy = Column(String(64), nullable=True)

    source = relationship("Source", back_populates="fetch_logs")
