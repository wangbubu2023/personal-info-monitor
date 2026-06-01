"""Normalized atom ORM models."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.orm import relationship

from app.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class Atom(Base):
    __tablename__ = "atoms"
    __table_args__ = (
        UniqueConstraint(
            "content_id",
            "source_sentence",
            "atom_type",
            name="uq_atom_content_sentence_type",
        ),
    )

    atom_id = Column(String(32), primary_key=True)
    content_id = Column(
        UUIDString,
        ForeignKey("contents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    atom_type = Column(String(16), nullable=False, index=True)
    domain = Column(String(32), nullable=False, index=True)
    source_sentence = Column(Text, nullable=False)
    source_url = Column(Text, nullable=False)
    atom_source = Column(String(255), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    verified = Column(Boolean, nullable=False, default=False, index=True)
    source_credibility = Column(Float, nullable=False)
    fact_confidence = Column(Float, nullable=False)
    schema_version = Column(Integer, nullable=False, default=2)

    # Lifecycle / evolution (Schema v2.1)
    status = Column(String(16), nullable=False, default="active", index=True)
    is_latest = Column(Boolean, nullable=False, default=True, index=True)
    supersedes_atom_id = Column(String(32), nullable=True)
    superseded_by_atom_id = Column(String(32), nullable=True)
    reconcile_group_id = Column(String(64), nullable=True, index=True)
    canonical_text = Column(Text, nullable=True)
    quality_score = Column(Float, nullable=True)
    quality_flags = Column(JSON, nullable=False, default=list)
    evidence_count = Column(Integer, nullable=False, default=1)
    tags = Column(JSON, nullable=False, default=list)
    extraction_run_id = Column(String(64), nullable=True)
    reconcile_reason = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=utcnow_naive,
        onupdate=utcnow_naive,
    )

    content = relationship("Content", back_populates="atoms")


class AtomRelation(Base):
    __tablename__ = "atom_relations"
    __table_args__ = (
        UniqueConstraint("atom_a", "atom_b", name="uq_atom_relation_pair"),
    )

    rel_id = Column(String(32), primary_key=True)
    atom_a = Column(
        String(32),
        ForeignKey("atoms.atom_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    atom_b = Column(
        String(32),
        ForeignKey("atoms.atom_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation_type = Column(String(16), nullable=False)
    direction = Column(String(8), nullable=False)
    verified = Column(Boolean, nullable=False, default=False)
    fact_confidence = Column(Float, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=utcnow_naive,
        onupdate=utcnow_naive,
    )


class AtomOperation(Base):
    """Audit log of every LLM/rule decision affecting an atom (HY-memory pipeline log)."""

    __tablename__ = "atom_operations"

    operation_id = Column(String(32), primary_key=True)
    operation_type = Column(String(16), nullable=False, index=True)
    content_id = Column(UUIDString, nullable=True, index=True)
    atom_id = Column(String(32), nullable=True, index=True)
    related_atom_ids = Column(JSON, nullable=False, default=list)
    model_provider = Column(String(64), nullable=True)
    model_name = Column(String(128), nullable=True)
    prompt = Column(Text, nullable=True)
    raw_response = Column(Text, nullable=True)
    parsed = Column(JSON, nullable=True)
    reason = Column(Text, nullable=True)
    quality_flags = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


class AtomIdSequence(Base):
    __tablename__ = "atom_id_sequences"

    prefix = Column(String(16), primary_key=True)
    last_seq = Column(Integer, nullable=False, default=0)
