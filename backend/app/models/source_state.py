"""M5B normalized source state tables kept alongside the legacy Source DTO."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text

from app.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class SourceFetchState(Base):
    __tablename__ = "source_fetch_state"
    __table_args__ = (Index("uq_source_fetch_state_source", "source_id", unique=True),)

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id = Column(UUIDString, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    last_fetched_at = Column(DateTime, nullable=True)
    last_content_id = Column(String(255), nullable=True)
    last_error = Column(Text, nullable=True)
    error_count = Column(Integer, nullable=False, default=0)
    failure_code = Column(String(64), nullable=True)
    failure_status = Column(Integer, nullable=True)  # noqa: V107
    failure_severity = Column(String(16), nullable=True)  # noqa: V107
    cooldown_until = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class SourceDiscoveryStats(Base):
    __tablename__ = "source_discovery_stats"
    __table_args__ = (Index("uq_source_discovery_stats_source", "source_id", unique=True),)

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id = Column(UUIDString, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    checked_at = Column(DateTime, nullable=True)
    total = Column(Integer, nullable=True)
    kept = Column(Integer, nullable=True)
    dropped = Column(JSON, nullable=False, default=dict)
    pagination = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class SourceSessionState(Base):
    __tablename__ = "source_session_state"
    __table_args__ = (Index("uq_source_session_state_source", "source_id", unique=True),)

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id = Column(UUIDString, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(16), nullable=True)
    reason = Column(String(64), nullable=True)
    suggested_action = Column(String(64), nullable=True)
    validated_at = Column(DateTime, nullable=True)
    details = Column(JSON, nullable=False, default=dict)
    alert_reason = Column(String(64), nullable=True)  # noqa: V107
    alert_sent_at = Column(DateTime, nullable=True)  # noqa: V107
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class SourcePolicy(Base):
    __tablename__ = "source_policy"
    __table_args__ = (Index("uq_source_policy_source", "source_id", unique=True),)

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id = Column(UUIDString, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    fetch_interval = Column(Integer, nullable=False, default=60)
    use_keyword_filter = Column(Boolean, nullable=False, default=False)
    auth_required = Column(Boolean, nullable=False, default=False)
    policy_version = Column(String(32), nullable=False, default="source-policy-v1")
    metadata_ = Column("metadata", JSON, nullable=False, default=dict)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


__all__ = ["SourceDiscoveryStats", "SourceFetchState", "SourcePolicy", "SourceSessionState"]
