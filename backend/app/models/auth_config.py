"""Authentication configuration models."""

import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum, JSON, String, Text
from sqlalchemy.orm import relationship

from app.utils.datetime import utcnow_naive
from app.database import Base, UUIDString


class AuthType(str, enum.Enum):
    """Type of authentication."""
    PASSWORD = "password"
    API_KEY = "api_key"
    OAUTH = "oauth"
    COOKIE = "cookie"


class AuthStatus(str, enum.Enum):
    """Authentication status."""
    ACTIVE = "active"
    EXPIRED = "expired"
    INVALID = "invalid"


class AuthConfig(Base):
    """Authentication configuration for websites requiring login."""

    __tablename__ = "auth_configs"

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=True)
    site_url = Column(Text, nullable=False)
    auth_type = Column(Enum(AuthType), nullable=False, default=AuthType.PASSWORD)
    is_shared = Column(Boolean, nullable=False, default=False)

    # Encrypted credentials
    credentials = Column(Text, nullable=True)

    # Session data (cookies, tokens, etc.)
    session_data = Column(Text, nullable=True)

    # Status
    status = Column(Enum(AuthStatus), default=AuthStatus.ACTIVE)
    last_validated_at = Column(DateTime, nullable=True)

    # Login page configuration
    login_url = Column(Text, nullable=True)
    login_selectors = Column(JSON, default=dict)

    # Timestamps
    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    # Relationships
    sources = relationship("Source", back_populates="auth_config")

    def __repr__(self) -> str:
        return f"<AuthConfig(id={self.id}, site_url='{self.site_url}', shared={self.is_shared})>"


class APIConfig(Base):
    """API configuration for third-party services."""

    __tablename__ = "api_configs"

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    platform = Column(String(50), nullable=False)
    name = Column(String(255), nullable=True)

    # Encrypted credentials
    encrypted_credentials = Column(Text, nullable=False)

    # Status and usage
    status = Column(Enum(AuthStatus), default=AuthStatus.ACTIVE)
    last_used_at = Column(DateTime, nullable=True)

    # Rate limiting info
    rate_limit_info = Column(JSON, default=dict)

    # Timestamps
    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    def __repr__(self) -> str:
        return f"<APIConfig(id={self.id}, platform='{self.platform}')>"
