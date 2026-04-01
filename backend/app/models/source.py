"""Source model for monitoring sources."""

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from app.utils.datetime import utcnow_naive
from app.database import Base, UUIDString


class SourceType(str, enum.Enum):
    """Type of content source."""
    WEBSITE = "website"
    RSS = "rss"
    X = "x"
    YOUTUBE = "youtube"
    PODCAST = "podcast"


class Source(Base):
    """Monitoring source configuration."""

    __tablename__ = "sources"
    __table_args__ = (
        Index("ix_source_last_fetched_at", "last_fetched_at"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    type = Column(Enum(SourceType), nullable=False)
    url = Column(Text, nullable=False)

    # Category relationship
    category_id = Column(UUIDString, ForeignKey("categories.id"), nullable=True)

    # Fetch settings
    fetch_interval = Column(Integer, default=60)  # Minutes
    enabled = Column(Boolean, default=True)
    priority = Column(Integer, default=0)

    # Authentication
    auth_required = Column(Boolean, default=False)
    auth_config_id = Column(UUIDString, ForeignKey("auth_configs.id"), nullable=True)

    # Status tracking
    last_fetched_at = Column(DateTime, nullable=True)
    last_content_id = Column(String(255), nullable=True)
    last_error = Column(Text, nullable=True)
    error_count = Column(Integer, default=0)

    # Additional configuration stored as JSON
    metadata_ = Column("metadata", JSON, default=dict)

    # Timestamps
    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    # Relationships
    category = relationship("Category", back_populates="sources")
    auth_config = relationship("AuthConfig", back_populates="sources")
    contents = relationship("Content", back_populates="source", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Source(id={self.id}, name='{self.name}', type={self.type})>"
