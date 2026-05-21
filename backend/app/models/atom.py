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


class AtomIdSequence(Base):
    __tablename__ = "atom_id_sequences"

    prefix = Column(String(16), primary_key=True)
    last_seq = Column(Integer, nullable=False, default=0)
