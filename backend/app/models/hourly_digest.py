"""Hourly digest model."""

import uuid
from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Index, Integer, JSON, String, Text, UniqueConstraint

from app.utils.datetime import utcnow_naive
from app.database import Base, UUIDString


class HourlyDigest(Base):
    """Stored hourly digest generated at top of each hour."""

    __tablename__ = "hourly_digests"
    __table_args__ = (
        UniqueConstraint("digest_date", "hour", name="uq_hourly_digest_date_hour"),
        Index("ix_hourly_digest_date_hour", "digest_date", "hour"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    digest_date = Column(Date, nullable=False)
    hour = Column(Integer, nullable=False)
    title = Column(String(100), nullable=False)
    summary = Column(Text, nullable=True)
    content_count = Column(Integer, default=0, nullable=False)
    sources = Column(JSON, default=list)

    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)
