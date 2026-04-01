"""Keyword model for content monitoring."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, String, Text

from app.utils.datetime import utcnow_naive
from app.database import Base, UUIDString


class MatchType(str, enum.Enum):
    """Type of keyword matching."""
    EXACT = "exact"
    CONTAINS = "contains"
    REGEX = "regex"


class Keyword(Base):
    """Keyword for content monitoring and alerts."""

    __tablename__ = "keywords"

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    keyword = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Matching configuration
    match_type = Column(Enum(MatchType), default=MatchType.CONTAINS)
    case_sensitive = Column(Boolean, default=False)

    # Notification settings
    notify = Column(Boolean, default=True)
    notify_email = Column(Boolean, default=False)

    # Styling
    color = Column(String(7), default="#ff4d4f")

    # Status
    enabled = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    def __repr__(self) -> str:
        return f"<Keyword(id={self.id}, keyword='{self.keyword}')>"
