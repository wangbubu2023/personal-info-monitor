"""Content model for storing fetched content."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.utils.datetime import utcnow_naive
from app.database import Base, UUIDString


class Content(Base):
    """Fetched content from monitoring sources."""

    __tablename__ = "contents"

    __table_args__ = (
        UniqueConstraint('source_id', 'external_id', name='uq_content_source_external_id'),
        Index('ix_content_source_external', 'source_id', 'external_id'),
        Index('ix_content_created_at', 'created_at'),
        Index('ix_content_publish_time', 'publish_time'),
        Index('ix_content_fetched_at', 'fetched_at'),
        Index('ix_content_updated_at', 'updated_at'),
        Index('ix_content_original_url', 'original_url'),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id = Column(UUIDString, ForeignKey("sources.id"), nullable=False)

    # Content identification
    external_id = Column(String(255), nullable=True)

    # Main content
    title = Column(Text, nullable=False)
    translated_title = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    translated_summary = Column(Text, nullable=True)
    original_url = Column(Text, nullable=False)

    # Full content
    # TODO(FTS5): Optional SQLite FTS5 virtual table + sync for title/summary/full_content search;
    # btree indexes on publish_time/fetched_at address list ordering; FTS5 is follow-up work.
    full_content = Column(Text, nullable=True)

    # Content type inherited from source
    content_type = Column(String(50), nullable=False)

    # Timestamps
    publish_time = Column(DateTime, nullable=True)
    fetched_at = Column(DateTime, default=utcnow_naive)

    # User interaction
    read_status = Column(Boolean, default=False)
    favorited = Column(Boolean, default=False)
    archived = Column(Boolean, default=False)
    is_user_edited = Column(Boolean, default=False)

    # Keyword matching results
    keyword_matches = Column(JSON, default=list)

    # Additional metadata
    metadata_ = Column("metadata", JSON, default=dict)

    # Timestamps
    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    # Relationships
    source = relationship("Source", back_populates="contents")

    def __repr__(self) -> str:
        safe_title = (self.title or "")[:50]
        return f"<Content(id={self.id}, title='{safe_title}...')>"
