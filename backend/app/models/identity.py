"""M5A identity, device, scoped session, and audit actor records."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, JSON, String, Text

from app.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class IdentityUser(Base):
    __tablename__ = "identity_users"
    __table_args__ = (Index("uq_identity_user_tenant_subject", "tenant_id", "subject", unique=True),)

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(128), nullable=False, default="default")
    subject = Column(String(255), nullable=False)
    email = Column(String(320), nullable=True)
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class IdentityDevice(Base):
    __tablename__ = "identity_devices"
    __table_args__ = (Index("ix_identity_device_tenant", "tenant_id", "status"),)

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(UUIDString, ForeignKey("identity_users.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(String(128), nullable=False, default="default")
    device_key = Column(String(128), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    revoked_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


class ServicePrincipal(Base):
    __tablename__ = "service_principals"
    __table_args__ = (Index("uq_service_principal_tenant_name", "tenant_id", "name", unique=True),)

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(128), nullable=False, default="default")
    name = Column(String(255), nullable=False)
    scopes = Column(JSON, nullable=False, default=list)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


class IdentitySession(Base):
    __tablename__ = "identity_sessions"
    __table_args__ = (
        Index("ix_identity_session_access_hash", "access_token_hash", unique=True),
        Index("ix_identity_session_refresh_hash", "refresh_token_hash", unique=True),
        Index("ix_identity_session_refresh_family", "refresh_family_id"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(UUIDString, ForeignKey("identity_users.id", ondelete="CASCADE"), nullable=False)
    device_id = Column(UUIDString, ForeignKey("identity_devices.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(String(128), nullable=False, default="default")
    scopes = Column(JSON, nullable=False, default=list)
    access_token_hash = Column(String(128), nullable=False)  # noqa: V107
    access_expires_at = Column(DateTime, nullable=False)
    refresh_family_id = Column(String(128), nullable=False)
    refresh_token_hash = Column(String(128), nullable=False)
    refresh_expires_at = Column(DateTime, nullable=False)
    refresh_used_at = Column(DateTime, nullable=True)
    rotated_from_id = Column(UUIDString, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    last_seen_at = Column(DateTime, nullable=False, default=utcnow_naive)


class AuditActor(Base):
    __tablename__ = "audit_actors"

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(128), nullable=False, default="default")
    actor_type = Column(String(32), nullable=False)
    actor_id = Column(String(128), nullable=False)
    action = Column(String(128), nullable=False)
    target_type = Column(String(64), nullable=True)
    target_id = Column(String(128), nullable=True)
    metadata_ = Column("metadata", JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


__all__ = ["AuditActor", "IdentityDevice", "IdentitySession", "IdentityUser", "ServicePrincipal"]
