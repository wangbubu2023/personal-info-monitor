"""Email schedule model for digest delivery."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, Text

from app.utils.datetime import utcnow_naive
from app.database import Base, UUIDString


class EmailSchedule(Base):
    """Email schedule configuration for digest delivery."""

    __tablename__ = "email_schedules"

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)

    # Recipients (stored as JSON array)
    recipients = Column(JSON, default=list)

    # Schedule configuration
    schedule_hour = Column(Integer, default=8)
    schedule_minute = Column(Integer, default=0)
    schedule_days = Column(JSON, default=[1, 2, 3, 4, 5])  # Mon-Fri

    # Content filter
    content_filter = Column(JSON, default=dict)

    # Template
    template = Column(String(50), default="default")
    subject_template = Column(String(255), default="📰 每日资讯简报 - {date}")

    # Status
    enabled = Column(Boolean, default=True)
    last_sent_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    def __repr__(self) -> str:
        return f"<EmailSchedule(id={self.id}, name='{self.name}')>"
