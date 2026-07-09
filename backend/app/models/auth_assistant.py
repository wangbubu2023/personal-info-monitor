"""Models for PIM Auth Assistant device pairing."""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Column, DateTime, Enum, JSON, String, Text

from app.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class AuthAssistantTokenStatus(str, enum.Enum):
    """Lifecycle status for one-time pairing tokens."""

    PENDING = "pending"
    CLAIMED = "claimed"
    EXPIRED = "expired"
    REVOKED = "revoked"


class AuthAssistantDeviceStatus(str, enum.Enum):
    """Lifecycle status for paired local Auth Assistant devices."""

    ACTIVE = "active"
    REVOKED = "revoked"


class AuthAssistantPairingToken(Base):
    """One-time token created from PIM Web and claimed by the local assistant."""

    __tablename__ = "auth_assistant_pairing_tokens"

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    token_hash = Column(String(128), nullable=False, unique=True, index=True)
    token_hint = Column(String(32), nullable=False)
    status = Column(Enum(AuthAssistantTokenStatus), nullable=False, default=AuthAssistantTokenStatus.PENDING)
    expires_at = Column(DateTime, nullable=False)
    claimed_at = Column(DateTime, nullable=True)
    device_id = Column(UUIDString, nullable=True)
    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)


class AuthAssistantDevice(Base):
    """Paired local Auth Assistant device with limited import permissions."""

    __tablename__ = "auth_assistant_devices"

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    token_hash = Column(String(128), nullable=False, unique=True, index=True)
    status = Column(Enum(AuthAssistantDeviceStatus), nullable=False, default=AuthAssistantDeviceStatus.ACTIVE)
    app_version = Column(String(64), nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    capabilities = Column(JSON, nullable=False, default=dict)
    metadata_ = Column("metadata", JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)


class AuthAssistantImportLog(Base):
    """Audit log for imports initiated by Auth Assistant devices."""

    __tablename__ = "auth_assistant_import_logs"

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id = Column(UUIDString, nullable=True, index=True)
    site_host = Column(String(255), nullable=True)
    profile_count = Column(String(32), nullable=False, default="1")
    result = Column(JSON, nullable=False, default=dict)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow_naive)
