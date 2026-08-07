"""WebSub and outbound Webhook integration records."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, JSON, String, Text

from app.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class WebSubSubscription(Base):
    __tablename__ = "websub_subscriptions"
    __table_args__ = (Index("uq_websub_source_topic", "source_id", "topic_url", unique=True),)

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id = Column(UUIDString, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    hub_url = Column(Text, nullable=False)
    topic_url = Column(Text, nullable=False)
    callback_path = Column(String(255), nullable=False)
    verify_token_hash = Column(String(128), nullable=False)
    secret_encrypted = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    lease_expires_at = Column(DateTime, nullable=True)
    last_verified_at = Column(DateTime, nullable=True)  # noqa: V107
    last_event_at = Column(DateTime, nullable=True)  # noqa: V107
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class WebSubDelivery(Base):
    __tablename__ = "websub_deliveries"
    __table_args__ = (Index("uq_websub_delivery_event_hash", "event_hash", unique=True),)

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    subscription_id = Column(UUIDString, ForeignKey("websub_subscriptions.id", ondelete="CASCADE"), nullable=False)
    event_hash = Column(String(128), nullable=False)
    payload_checksum = Column(String(128), nullable=False)  # noqa: V107
    item_count = Column(String(16), nullable=False, default="0")
    status = Column(String(20), nullable=False, default="accepted")
    fetch_job_id = Column(UUIDString, nullable=True)
    received_at = Column(DateTime, nullable=False, default=utcnow_naive)  # noqa: V107


class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"
    __table_args__ = (Index("uq_webhook_target", "target_url", unique=True),)

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    target_url = Column(Text, nullable=False)
    event_filters = Column(JSON, nullable=False, default=list)
    secret_encrypted = Column(Text, nullable=False)
    secret_key_version = Column(String(32), nullable=False, default="v1")
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


__all__ = ["WebSubDelivery", "WebSubSubscription", "WebhookSubscription"]
