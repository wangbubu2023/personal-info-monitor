"""Persisted system settings model."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, JSON, String

from app.utils.datetime import utcnow_naive
from app.database import Base, UUIDString


class SystemSetting(Base):
    """Key-value storage for runtime system settings."""

    __tablename__ = "system_settings"

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    key = Column(String(100), nullable=False, unique=True, index=True)
    value = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    def __repr__(self) -> str:
        return f"<SystemSetting(key={self.key})>"
