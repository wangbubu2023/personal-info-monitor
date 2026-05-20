"""ContentAtomBundle ORM — schema-versioned structured atoms per Content row.

Phase 6 of the modular refactor introduces the optional ``atoms`` layer:
events / entities / relations extracted from a finalized ``Content``
row. The whole layer stays inert unless the operator opts in via
``ATOMS_ENABLED=true``; nothing in the default ``fetch → ingest →
enrich`` main path depends on atoms.

Each row stores one *bundle* for one content_id. ``schema_version`` is
the on-disk shape version — readers must refuse bundles they do not
understand. The bundle payload is stored as JSON (SQLite/Postgres JSON
column) with three top-level keys (``events`` / ``entities`` /
``relations``) plus an opaque ``metadata`` envelope.

The unique constraint on ``content_id`` keeps the relation 1-to-1 so
:func:`app.domains.atoms.atomizer.atomize_content` can stay idempotent
through ``ON CONFLICT (content_id) DO UPDATE``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class ContentAtomBundle(Base):
    """Schema-versioned bundle of structured atoms for one Content row."""

    __tablename__ = "content_atom_bundles"

    __table_args__ = (
        UniqueConstraint("content_id", name="uq_content_atom_bundle_content_id"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    content_id = Column(
        UUIDString,
        ForeignKey("contents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    schema_version = Column(Integer, nullable=False, default=1)
    events = Column(JSON, nullable=False, default=list)
    entities = Column(JSON, nullable=False, default=list)
    relations = Column(JSON, nullable=False, default=list)
    bundle_metadata = Column(JSON, nullable=False, default=dict)

    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=utcnow_naive,
        onupdate=utcnow_naive,
    )

    content = relationship("Content")
