"""Topic domain models."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import relationship

from app.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class Topic(Base):
    """一级 Topic 实体模型。"""

    __tablename__ = "topics"

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    creation_type = Column(String(20), default="manual", nullable=False)  # rule, entity, manual
    rule_spec = Column(JSON, nullable=True)  # 例如 {"keywords": ["AI"], "entities": ["NVIDIA"]}
    status = Column(String(20), default="active", nullable=False)  # active, archived

    created_at = Column(DateTime, default=utcnow_naive, nullable=False)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive, nullable=False)

    associations = relationship("TopicEventAssociation", back_populates="topic", cascade="all, delete-orphan")


class TopicEventAssociation(Base):
    """Topic 与 ContentEvent 之间的多对多关联维表。"""

    __tablename__ = "topic_event_associations"
    __table_args__ = (Index("idx_topic_event_unique", "topic_id", "event_id", unique=True),)

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    topic_id = Column(UUIDString, ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    event_id = Column(String(32), ForeignKey("content_events.event_id", ondelete="CASCADE"), nullable=False)
    associated_at = Column(DateTime, default=utcnow_naive, nullable=False)

    topic = relationship("Topic", back_populates="associations")
    event = relationship("ContentEvent")
