"""Tests for atom lifecycle status machine and operation log."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domains.atoms.operations import SqlAtomOperationRepository
from app.domains.atoms.repository import AtomListFilters, SqlAtomRepository
from app.domains.atoms.types import AtomCreate, InfoAtomPayload
from app.domains.atoms.vocab import (
    AtomOperationType,
    AtomStatus,
    AtomType,
    Domain,
    SubjectType,
    Validity,
    WhatType,
)
from app.models import Content, Source
from app.models.atom import AtomOperation
from app.models.source import SourceType


@pytest.fixture
def sync_session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'status.db'}", future=True)
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
            title="Status test",
            original_url="https://demo.test/a",
            full_content="正文",
            content_type="article",
            publish_time=datetime(2026, 5, 20, 9, 30, 0),
            fetched_at=datetime(2026, 5, 20, 9, 30, 0),
        )
        session.add(content)
        session.commit()
        return content.id
    finally:
        session.close()


def _info_atom(content_id: str, sentence: str, *, verified: bool = False) -> AtomCreate:
    return AtomCreate(
        content_id=content_id,
        source_url="https://demo.test/a",
        source_sentence=sentence,
        domain=Domain.TECH,
        atom_source="财新",
        source_credibility=0.9,
        fact_confidence=0.95,
        verified=verified,
        atom_type=AtomType.INFO,
        payload=InfoAtomPayload(
            who=[{"name": "华为", "type": SubjectType.COMPANY}],
            what_type=WhatType.PRODUCT,
            what="华为发布芯片",
            entities=["华为"],
            validity=Validity.MEDIUM,
        ),
    )


def test_new_atom_defaults_active_latest(sync_session_factory, seeded_content):
    repo = SqlAtomRepository(sync_session_factory)
    created = repo.create_atom(_info_atom(seeded_content, "华为发布旗舰芯片麒麟X1面向高端市场。"))
    assert created.status == AtomStatus.ACTIVE
    assert created.is_latest is True
    assert created.evidence_count == 1


def test_missing_atom_becomes_shadow_not_deleted(sync_session_factory, seeded_content):
    repo = SqlAtomRepository(sync_session_factory)
    s1 = "华为发布旗舰芯片麒麟X1面向高端市场。"
    s2 = "小米发布新款汽车SU8进军高端市场。"
    repo.upsert_atoms_for_content(seeded_content, [_info_atom(seeded_content, s1), _info_atom(seeded_content, s2)])

    # Re-extract: only s1 survives. s2 should be shadowed, not removed.
    repo.upsert_atoms_for_content(seeded_content, [_info_atom(seeded_content, s1)])

    rows = repo.list_atoms_for_content(seeded_content)
    assert len(rows) == 2
    by_sentence = {r.source_sentence: r for r in rows}
    assert by_sentence[s1].status == AtomStatus.ACTIVE
    assert by_sentence[s2].status == AtomStatus.SHADOW
    assert "missing_in_latest_extraction" in by_sentence[s2].quality_flags


def test_active_only_filter(sync_session_factory, seeded_content):
    repo = SqlAtomRepository(sync_session_factory)
    s1 = "华为发布旗舰芯片麒麟X1面向高端市场。"
    s2 = "小米发布新款汽车SU8进军高端市场。"
    repo.upsert_atoms_for_content(seeded_content, [_info_atom(seeded_content, s1), _info_atom(seeded_content, s2)])
    repo.upsert_atoms_for_content(seeded_content, [_info_atom(seeded_content, s1)])

    active = repo.list_atoms_for_content(seeded_content, active_only=True)
    assert len(active) == 1
    assert active[0].source_sentence == s1


def test_list_atoms_status_filter(sync_session_factory, seeded_content):
    repo = SqlAtomRepository(sync_session_factory)
    s1 = "华为发布旗舰芯片麒麟X1面向高端市场。"
    s2 = "小米发布新款汽车SU8进军高端市场。"
    repo.upsert_atoms_for_content(seeded_content, [_info_atom(seeded_content, s1), _info_atom(seeded_content, s2)])
    repo.upsert_atoms_for_content(seeded_content, [_info_atom(seeded_content, s1)])

    active, total = repo.list_atoms(AtomListFilters(status="active"))
    assert total == 1
    shadow, shadow_total = repo.list_atoms(AtomListFilters(status="shadow"))
    assert shadow_total == 1


def test_verified_atom_not_shadowed(sync_session_factory, seeded_content):
    repo = SqlAtomRepository(sync_session_factory)
    s1 = "华为发布旗舰芯片麒麟X1面向高端市场。"
    repo.upsert_atoms_for_content(seeded_content, [_info_atom(seeded_content, s1, verified=True)])
    repo.upsert_atoms_for_content(seeded_content, [])
    rows = repo.list_atoms_for_content(seeded_content)
    assert len(rows) == 1
    assert rows[0].status == AtomStatus.ACTIVE
    assert rows[0].verified is True


def test_quality_stats_shape(sync_session_factory, seeded_content):
    repo = SqlAtomRepository(sync_session_factory)
    s1 = "华为发布旗舰芯片麒麟X1面向高端市场。"
    s2 = "小米发布新款汽车SU8进军高端市场。"
    repo.upsert_atoms_for_content(seeded_content, [_info_atom(seeded_content, s1), _info_atom(seeded_content, s2)])
    repo.upsert_atoms_for_content(seeded_content, [_info_atom(seeded_content, s1)])

    stats = repo.quality_stats()
    assert stats["total_atoms"] == 2
    assert stats["active_atoms"] == 1
    assert stats["shadow_atoms"] == 1
    assert "fact_confidence_histogram" in stats
    assert stats["p95_atoms_per_content"] >= 1


def test_operation_log_records(sync_session_factory):
    op_repo = SqlAtomOperationRepository(sync_session_factory)
    op_id = op_repo.record(
        operation_type=AtomOperationType.EXTRACT,
        content_id="content-1",
        related_atom_ids=["ATOM-1"],
        reason="extraction_run",
        parsed={"atom_count": 3},
    )
    assert op_id is not None
    session = sync_session_factory()
    try:
        row = session.get(AtomOperation, op_id)
        assert row is not None
        assert row.operation_type == "extract"
        assert row.parsed == {"atom_count": 3}
    finally:
        session.close()
