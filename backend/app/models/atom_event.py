"""L3 event-summary and L5 knowledge-entity ORM models."""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)

from app.database import Base
from app.utils.datetime import utcnow_naive


class EventCluster(Base):
    __tablename__ = "event_clusters"

    event_id = Column(String(32), primary_key=True)
    title = Column(Text, nullable=False)
    domain = Column(String(32), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="active", index=True)
    first_seen_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    canonical_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class EventClusterAtom(Base):
    __tablename__ = "event_cluster_atoms"
    __table_args__ = (
        UniqueConstraint("event_id", "atom_id", name="uq_event_cluster_atom"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(
        String(32),
        ForeignKey("event_clusters.event_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    atom_id = Column(String(32), nullable=False, index=True)
    role = Column(String(16), nullable=False, default="background")
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


class EventSummary(Base):
    __tablename__ = "event_summaries"

    summary_id = Column(String(32), primary_key=True)
    event_id = Column(
        String(32),
        ForeignKey("event_clusters.event_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    window_start = Column(DateTime, nullable=True)
    window_end = Column(DateTime, nullable=True)
    summary = Column(Text, nullable=False)
    model = Column(String(128), nullable=True)
    source_atom_ids = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


class KnowledgeEntity(Base):
    __tablename__ = "knowledge_entities"

    entity_id = Column(String(32), primary_key=True)
    canonical_name = Column(String(255), nullable=False, index=True)
    entity_type = Column(String(32), nullable=False, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class EntityAlias(Base):
    __tablename__ = "entity_aliases"
    __table_args__ = (
        UniqueConstraint("alias", "entity_id", name="uq_entity_alias"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    alias = Column(String(255), nullable=False, index=True)
    entity_id = Column(
        String(32),
        ForeignKey("knowledge_entities.entity_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source = Column(String(64), nullable=True)


class AtomEntity(Base):
    __tablename__ = "atom_entities"
    __table_args__ = (
        UniqueConstraint("atom_id", "entity_id", "role", name="uq_atom_entity_role"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    atom_id = Column(String(32), nullable=False, index=True)
    entity_id = Column(
        String(32),
        ForeignKey("knowledge_entities.entity_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(32), nullable=True)


class EntityRelation(Base):
    __tablename__ = "entity_relations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    subject_entity_id = Column(String(32), nullable=False, index=True)
    relation_type = Column(String(32), nullable=False)
    object_entity_id = Column(String(32), nullable=False, index=True)
    evidence_atom_id = Column(String(32), nullable=True)
    confidence = Column(Float, nullable=False, default=0.7)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
