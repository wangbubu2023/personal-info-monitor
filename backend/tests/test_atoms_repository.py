"""Normalized atoms layer tests."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domains.atoms import CURRENT_SCHEMA_VERSION, SqlAtomReader, SqlAtomRepository, atomize_content
from app.domains.atoms.id_gen import next_atom_id
from app.domains.atoms.types import AtomCreate, AtomUpdate, InfoAtomPayload
from app.domains.atoms.vocab import AtomType, Domain, SubjectType, Validity, WhatType
from app.models import Content, Source
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
            title="Atoms normalized",
            original_url="https://demo.test/articles/atoms",
            full_content="华为于2026年5月18日在深圳发布了全新旗舰芯片麒麟X1。",
            content_type="article",
            publish_time=datetime(2026, 5, 20, 9, 30, 0),
            fetched_at=datetime(2026, 5, 20, 9, 30, 0),
        )
        session.add(content)
        session.commit()
        return content.id
    finally:
        session.close()


def _info_atom(content_id: str, *, verified: bool = False) -> AtomCreate:
    return AtomCreate(
        content_id=content_id,
        source_url="https://demo.test/articles/atoms",
        source_sentence="华为于2026年5月18日在深圳发布了全新旗舰芯片麒麟X1。",
        domain=Domain.TECH,
        atom_source="财新",
        source_credibility=0.95,
        fact_confidence=0.98,
        verified=verified,
        atom_type=AtomType.INFO,
        payload=InfoAtomPayload(
            when="2026-05-18",
            where="深圳",
            who=[{"name": "华为", "type": SubjectType.COMPANY}],
            what_type=WhatType.PRODUCT,
            what="华为发布旗舰芯片麒麟X1",
            entities=["华为", "麒麟X1", "深圳"],
            validity=Validity.MEDIUM,
        ),
    )


def test_next_atom_id_increments(sync_session_factory):
    session = sync_session_factory()
    try:
        first = next_atom_id(session)
        second = next_atom_id(session)
        session.commit()
        assert first != second
        assert first.startswith("ATOM-")
    finally:
        session.close()


def test_create_and_get_atom(sync_session_factory, seeded_content):
    repo = SqlAtomRepository(sync_session_factory)
    created = repo.create_atom(_info_atom(seeded_content))
    assert created.atom_id.startswith("ATOM-")
    assert created.schema_version == CURRENT_SCHEMA_VERSION

    fetched = repo.get_atom(created.atom_id)
    assert fetched is not None
    assert fetched.payload["what"] == "华为发布旗舰芯片麒麟X1"


def test_upsert_preserves_atom_id(sync_session_factory, seeded_content):
    repo = SqlAtomRepository(sync_session_factory)
    first = repo.upsert_atoms_for_content(seeded_content, [_info_atom(seeded_content)])
    updated = _info_atom(seeded_content)
    second = repo.upsert_atoms_for_content(seeded_content, [updated])
    assert first[0].atom_id == second[0].atom_id


def test_upsert_keeps_verified_atoms(sync_session_factory, seeded_content):
    repo = SqlAtomRepository(sync_session_factory)
    repo.upsert_atoms_for_content(seeded_content, [_info_atom(seeded_content, verified=True)])
    repo.upsert_atoms_for_content(seeded_content, [])
    remaining = repo.list_atoms_for_content(seeded_content)
    assert len(remaining) == 1
    assert remaining[0].verified is True


def test_update_atom_verified(sync_session_factory, seeded_content):
    repo = SqlAtomRepository(sync_session_factory)
    created = repo.create_atom(_info_atom(seeded_content))
    updated = repo.update_atom(created.atom_id, AtomUpdate(verified=True))
    assert updated is not None
    assert updated.verified is True


def test_atomize_returns_false_when_flag_disabled(monkeypatch, seeded_content):
    monkeypatch.delenv("ATOMS_ENABLED", raising=False)
    assert atomize_content(seeded_content) is False


def test_reader_returns_empty_when_flag_disabled(monkeypatch, sync_session_factory, seeded_content):
    monkeypatch.delenv("ATOMS_ENABLED", raising=False)
    repo = SqlAtomRepository(sync_session_factory)
    repo.create_atom(_info_atom(seeded_content))
    reader = SqlAtomReader(sync_session_factory)
    assert reader.get_atoms_for_content(seeded_content) == ()


def test_reader_returns_atoms_when_enabled(monkeypatch, sync_session_factory, seeded_content):
    monkeypatch.setenv("ATOMS_ENABLED", "true")
    repo = SqlAtomRepository(sync_session_factory)
    repo.create_atom(_info_atom(seeded_content))
    reader = SqlAtomReader(sync_session_factory)
    atoms = reader.get_atoms_for_content(seeded_content)
    assert len(atoms) == 1
    assert atoms[0].atom_type == AtomType.INFO


def test_stats(sync_session_factory, seeded_content):
    repo = SqlAtomRepository(sync_session_factory)
    repo.create_atom(_info_atom(seeded_content))
    stats = repo.stats()
    assert stats["total"] == 1
    assert stats["by_type"]["信息"] == 1
