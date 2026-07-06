"""Source model for monitoring sources."""

import enum
import uuid

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

    # Fetch settings
    fetch_interval = Column(Integer, default=60)  # Minutes
    enabled = Column(Boolean, default=True)
    use_keyword_filter = Column(Boolean, default=False)

    # Authentication
    auth_required = Column(Boolean, default=False)
    auth_config_id = Column(UUIDString, ForeignKey("auth_configs.id"), nullable=True)

    # Status tracking
    last_fetched_at = Column(DateTime, nullable=True)
    last_content_id = Column(String(255), nullable=True)
    last_error = Column(Text, nullable=True)
    error_count = Column(Integer, default=0)
    fetch_failure_code = Column(String(64), nullable=True)
    fetch_failure_status = Column(Integer, nullable=True)
    fetch_failure_severity = Column(String(16), nullable=True)
    fetch_failure_retryable = Column(Boolean, nullable=True)
    fetch_failure_consecutive = Column(Integer, default=0)
    fetch_failure_updated_at = Column(DateTime, nullable=True)
    fetch_cooldown_until = Column(DateTime, nullable=True)
    rss_health_status = Column(String(16), nullable=True)
    rss_health_healthy = Column(Boolean, nullable=True)
    rss_health_item_count = Column(Integer, nullable=True)
    rss_health_last_update = Column(DateTime, nullable=True)
    rss_health_stale_days = Column(Integer, nullable=True)
    rss_health_reason = Column(String(64), nullable=True)
    rss_health_checked_at = Column(DateTime, nullable=True)
    rss_health_feed_url = Column(Text, nullable=True)
    discovery_checked_at = Column(DateTime, nullable=True)
    discovery_total = Column(Integer, nullable=True)
    discovery_kept = Column(Integer, nullable=True)
    discovery_dropped_no_url = Column(Integer, nullable=True)
    discovery_dropped_off_domain = Column(Integer, nullable=True)
    discovery_dropped_deny = Column(Integer, nullable=True)
    discovery_dropped_allow_miss = Column(Integer, nullable=True)
    discovery_dropped_non_article_url = Column(Integer, nullable=True)
    discovery_dropped_short_title = Column(Integer, nullable=True)
    discovery_dropped_duplicate = Column(Integer, nullable=True)
    discovery_dropped_stale = Column(Integer, nullable=True)
    discovery_truncated = Column(Integer, nullable=True)
    discovery_listing_urls_configured = Column(Integer, nullable=True)
    discovery_listing_pages_total = Column(Integer, nullable=True)
    discovery_listing_pages_fetched = Column(Integer, nullable=True)
    discovery_listing_pages_failed = Column(Integer, nullable=True)
    discovery_pagination_max_pages = Column(Integer, nullable=True)
    last_fetch_outcome_code = Column(String(64), nullable=True)
    last_fetch_outcome_severity = Column(String(16), nullable=True)
    last_fetch_outcome_message = Column(Text, nullable=True)
    last_fetch_outcome_updated_at = Column(DateTime, nullable=True)
    session_health_status = Column(String(16), nullable=True)
    session_health_reason = Column(String(64), nullable=True)
    session_health_suggested_action = Column(String(64), nullable=True)
    session_health_validated_at = Column(DateTime, nullable=True)
    session_health_details = Column(JSON, nullable=True)
    session_health_alert_reason = Column(String(64), nullable=True)
    session_health_alert_sent_at = Column(DateTime, nullable=True)

    # Additional configuration stored as JSON
    metadata_ = Column("metadata", JSON, default=dict)

    # Timestamps
    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    auth_config = relationship("AuthConfig", back_populates="sources")
    contents = relationship("Content", back_populates="source", cascade="all, delete-orphan")
    fetch_logs = relationship("SourceFetchLog", back_populates="source", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Source(id={self.id}, name='{self.name}', type={self.type})>"
