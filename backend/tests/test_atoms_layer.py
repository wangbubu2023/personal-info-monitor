"""Phase 6 — atoms layer: idempotency, feature-flag gating, reader contract.

These tests pin the invariants documented in ``app/domains/atoms/__init__.py``:

* ``ATOMS_ENABLED=false`` keeps the layer fully inert (no rows written,
  no rows read).
* ``atomize_content`` is idempotent — repeated calls overwrite, never
  duplicate.
* ``atomize_content`` *never* raises, even when the SQLAlchemy session
  blows up.
* :class:`SqlAtomReader` returns the contract DTO unchanged for the
  current schema version and refuses unknown schema versions.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domains.atoms import (
    CURRENT_SCHEMA_VERSION,
    SqlAtomReader,
    atom_bundle_from_row,
    atomize_content,
)
from app.domains.contracts.atoms import AtomBundle
from app.models import Content, ContentAtomBundle, Source
from app.models.source import SourceType


@pytest.fixture
def sync_session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'atoms.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def seeded_content(sync_session_factory):
    """Insert one Source + one Content row and return the content_id."""
    session = sync_session_factory()
    try:
        source = Source(
            id="src-1",
            name="Demo",
            type=SourceType.RSS,
            url="https://demo.test/feed",
            fetch_interval=60,
        )
        session.add(source)
        session.flush()

        content = Content(
            id="content-1",
            source_id=source.id,
            external_id="ext-1",
            title="Phase 6 atoms ship",
            original_url="https://demo.test/articles/atoms",
            full_content="The atoms layer is on.",
            content_type="article",
            publish_time=datetime(2026, 5, 20, 9, 30, 0),
            fetched_at=datetime(2026, 5, 20, 9, 30, 0),
        )
        session.add(content)
        session.commit()
        return content.id
    finally:
        session.close()


def test_atomize_returns_false_when_flag_disabled(monkeypatch, sync_session_factory, seeded_content):
    """ATOMS_ENABLED=false ⇒ atomize_content is a no-op and writes nothing."""
    monkeypatch.delenv("ATOMS_ENABLED", raising=False)
    with patch("app.domains.atoms.atomizer.SessionLocal", sync_session_factory):
        assert atomize_content(seeded_content) is False

    with sync_session_factory() as session:
        assert session.query(ContentAtomBundle).count() == 0


def test_atomize_writes_bundle_when_flag_enabled(monkeypatch, sync_session_factory, seeded_content):
    """Flag on ⇒ exactly one bundle row at schema_version=CURRENT_SCHEMA_VERSION."""
    monkeypatch.setenv("ATOMS_ENABLED", "true")
    with patch("app.domains.atoms.atomizer.SessionLocal", sync_session_factory):
        assert atomize_content(seeded_content) is True

    with sync_session_factory() as session:
        rows = session.query(ContentAtomBundle).all()
        assert len(rows) == 1
        bundle = rows[0]
        assert bundle.content_id == seeded_content
        assert bundle.schema_version == CURRENT_SCHEMA_VERSION
        assert bundle.events and bundle.events[0]["kind"] == "headline"
        assert bundle.entities and bundle.entities[0]["kind"] == "host"
        assert bundle.entities[0]["value"] == "demo.test"
        assert bundle.relations == []
        assert bundle.bundle_metadata["extractor"] == "default-heuristic"


def test_atomize_is_idempotent(monkeypatch, sync_session_factory, seeded_content):
    """Calling atomize_content twice keeps exactly one row (UPDATE not INSERT)."""
    monkeypatch.setenv("ATOMS_ENABLED", "true")
    with patch("app.domains.atoms.atomizer.SessionLocal", sync_session_factory):
        assert atomize_content(seeded_content) is True
        assert atomize_content(seeded_content) is True

    with sync_session_factory() as session:
        assert session.query(ContentAtomBundle).count() == 1


def test_atomize_swallows_exceptions(monkeypatch):
    """Atomize never propagates exceptions — that's the Phase 6 invariant."""
    monkeypatch.setenv("ATOMS_ENABLED", "true")
    broken_session = MagicMock()
    broken_session.query.side_effect = RuntimeError("db is on fire")
    broken_session.rollback = MagicMock()
    broken_session.close = MagicMock()

    with patch("app.domains.atoms.atomizer.SessionLocal", return_value=broken_session):
        result = atomize_content("any-id")

    assert result is False
    broken_session.rollback.assert_called_once()
    broken_session.close.assert_called_once()


def test_atomize_missing_content_returns_false(monkeypatch, sync_session_factory):
    """Missing content row ⇒ atomize returns False and writes nothing."""
    monkeypatch.setenv("ATOMS_ENABLED", "true")
    with patch("app.domains.atoms.atomizer.SessionLocal", sync_session_factory):
        assert atomize_content("nope-id") is False

    with sync_session_factory() as session:
        assert session.query(ContentAtomBundle).count() == 0


def test_reader_returns_none_when_flag_disabled(monkeypatch, sync_session_factory, seeded_content):
    """Reader short-circuits to None when ATOMS_ENABLED=false (even if row exists)."""
    monkeypatch.setenv("ATOMS_ENABLED", "true")
    with patch("app.domains.atoms.atomizer.SessionLocal", sync_session_factory):
        atomize_content(seeded_content)
    monkeypatch.setenv("ATOMS_ENABLED", "false")

    reader = SqlAtomReader(sync_session_factory)
    assert reader.get_bundle(seeded_content) is None


def test_reader_returns_contract_dto(monkeypatch, sync_session_factory, seeded_content):
    """Reader returns an AtomBundle contract DTO mirroring the stored row."""
    monkeypatch.setenv("ATOMS_ENABLED", "true")
    with patch("app.domains.atoms.atomizer.SessionLocal", sync_session_factory):
        atomize_content(seeded_content)

    reader = SqlAtomReader(sync_session_factory)
    bundle = reader.get_bundle(seeded_content)

    assert isinstance(bundle, AtomBundle)
    assert bundle.content_id == seeded_content
    assert bundle.schema_version == CURRENT_SCHEMA_VERSION
    assert bundle.events[0]["title"] == "Phase 6 atoms ship"


def test_reader_refuses_unknown_schema_version(monkeypatch, sync_session_factory, seeded_content):
    """Reader returns None for rows at an unsupported schema version."""
    monkeypatch.setenv("ATOMS_ENABLED", "true")
    session = sync_session_factory()
    try:
        bundle = ContentAtomBundle(
            content_id=seeded_content,
            schema_version=999,
            events=[],
            entities=[],
            relations=[],
            bundle_metadata={},
        )
        session.add(bundle)
        session.commit()
    finally:
        session.close()

    reader = SqlAtomReader(sync_session_factory)
    assert reader.get_bundle(seeded_content) is None


def test_atom_bundle_from_row_handles_none():
    """The conversion helper tolerates a None row (empty query result)."""
    assert atom_bundle_from_row(None) is None
