"""Stable content-level Event v0 models.

These tables intentionally separate event semantics from duplicate grouping:

- ``contents.duplicate_*`` answers "is this the same/near-same article?"
- ``content_events`` answers "what real-world event is this about?"
- ``content_event_memberships`` links many reports to one stable event
- ``content_event_snapshots`` stores brief/report versions for reading history
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class ContentEvent(Base):
    """Stable event identity for PIM content clusters."""

    __tablename__ = "content_events"
    __table_args__ = (
        Index("ix_content_events_event_key", "event_key"),
        Index("ix_content_events_last_seen", "last_seen_at"),
        Index("ix_content_events_status", "status"),
    )

    event_id = Column(String(32), primary_key=True)
    event_key = Column(String(128), nullable=False, unique=True)
    title = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="active")
    first_seen_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    importance_score = Column(Float, nullable=True)
    incremental_score = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)
    independent_source_count = Column(Integer, nullable=False, default=0)
    source_names = Column(JSON, nullable=False, default=list)
    metadata_ = Column("metadata", JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class ContentEventMembership(Base):
    """Content membership in a stable event."""

    __tablename__ = "content_event_memberships"
    __table_args__ = (
        UniqueConstraint("event_id", "content_id", name="uq_content_event_membership"),
        Index("ix_content_event_memberships_event", "event_id"),
        Index("ix_content_event_memberships_content", "content_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(32), ForeignKey("content_events.event_id", ondelete="CASCADE"), nullable=False)
    content_id = Column(UUIDString, ForeignKey("contents.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(24), nullable=False, default="supporting")
    confidence = Column(Float, nullable=True)
    evidence = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


class ContentEventSnapshot(Base):
    """Versioned event brief/report snapshot."""

    __tablename__ = "content_event_snapshots"
    __table_args__ = (
        UniqueConstraint("event_id", "version", name="uq_content_event_snapshot_version"),
        Index("ix_content_event_snapshots_event", "event_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(32), ForeignKey("content_events.event_id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    title = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    what_changed = Column(Text, nullable=True)
    why_matters = Column(Text, nullable=True)
    source_content_ids = Column(JSON, nullable=False, default=list)
    metadata_ = Column("metadata", JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
