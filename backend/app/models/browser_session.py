"""Persistent Playwright browser session model."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, JSON, String, Text
from sqlalchemy.orm import relationship

from app.utils.datetime import utcnow_naive
from app.database import Base, UUIDString


class BrowserSessionStatus(str, enum.Enum):
    """Validation status for persistent browser sessions."""

    ACTIVE = "active"
    NEEDS_LOGIN = "needs_login"
    ERROR = "error"


class BrowserSession(Base):
    """Persistent browser profile/session used for paywalled fetches."""

    __tablename__ = "browser_sessions"

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    site_url = Column(Text, nullable=False)
    site_host = Column(String(255), nullable=False, index=True, unique=True)
    profile_name = Column(String(255), nullable=False, unique=True)
    user_data_dir = Column(Text, nullable=False)
    storage_state_path = Column(Text, nullable=True)

    auth_config_id = Column(UUIDString, ForeignKey("auth_configs.id"), nullable=True)

    status = Column(Enum(BrowserSessionStatus), nullable=False, default=BrowserSessionStatus.NEEDS_LOGIN)
    last_validated_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSON, default=dict)

    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    auth_config = relationship("AuthConfig")

    def __repr__(self) -> str:
        return f"<BrowserSession(id={self.id}, host={self.site_host}, status={self.status})>"
