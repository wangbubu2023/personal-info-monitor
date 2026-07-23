"""One-time Web bootstrap codes and revocable HttpOnly sessions."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, Index, String

from app.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class BootstrapCode(Base):
    __tablename__ = "bootstrap_codes"
    __table_args__ = (Index("ix_bootstrap_codes_hash", "code_hash", unique=True),)

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    code_hash = Column(String(64), nullable=False)
    actor = Column(String(128), nullable=False, default="local-cli")
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    revoked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


class WebSession(Base):
    __tablename__ = "web_sessions"
    __table_args__ = (
        Index("ix_web_sessions_token_hash", "token_hash", unique=True),
        Index("ix_web_sessions_expires", "revoked_at", "absolute_expires_at"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    token_hash = Column(String(64), nullable=False)
    actor = Column(String(128), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    last_seen_at = Column(DateTime, nullable=False, default=utcnow_naive)
    idle_expires_at = Column(DateTime, nullable=False)
    absolute_expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    rotated_from_id = Column(UUIDString, nullable=True)


__all__ = ["BootstrapCode", "WebSession"]
