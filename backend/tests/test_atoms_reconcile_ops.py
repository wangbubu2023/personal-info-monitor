"""Tests for atom reconcile op parsing and transactional application."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domains.atoms.atom_reconcile.apply import AtomReconcileApplier
from app.domains.atoms.atom_reconcile.prompts import parse_reconcile_op
from app.domains.atoms.atom_reconcile.types import AtomReconcileOp, ReconcileOpType
from app.domains.atoms.canonical import build_canonical_text
from app.domains.atoms.repository import SqlAtomRepository
from app.domains.atoms.types import AtomCreate, InfoAtomPayload
from app.domains.atoms.vocab import (
    AtomStatus,
    AtomType,
    Domain,
    RelationType,
    SubjectType,
    Validity,
    WhatType,
)
from app.models import Content, Source
from app.models.atom import Atom, AtomRelation
from app.models.source import SourceType


@pytest.fixture
def sync_session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'reconcile.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def two_contents(sync_session_factory):
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
        for cid in ("content-1", "content-2"):
            session.add(
                Content(
                    id=cid,
                    source_id=source.id,
                    external_id=f"ext-{cid}",
                    title="t",
                    original_url=f"https://demo.test/{cid}",
                    full_content="正文",
                    content_type="article",
                    publish_time=datetime(2026, 5, 20, 9, 30, 0),
                    fetched_at=datetime(2026, 5, 20, 9, 30, 0),
                )
            )
        session.commit()
    finally:
        session.close()


def _atom(content_id: str, sentence: str, what: str) -> AtomCreate:
    return AtomCreate(
        content_id=content_id,
        source_url="https://demo.test/a",
        source_sentence=sentence,
        domain=Domain.TECH,
        atom_source="财新",
        source_credibility=0.9,
        fact_confidence=0.95,
        verified=False,
        atom_type=AtomType.INFO,
        payload=InfoAtomPayload(
            who=[{"name": "华为", "type": SubjectType.COMPANY}],
            what_type=WhatType.PRODUCT,
            what=what,
            entities=["华为"],
            validity=Validity.MEDIUM,
        ),
    )


def test_parse_reconcile_op_valid():
    op = parse_reconcile_op(
        '{"op":"SUPERSEDE","atom_id":"ATOM-1","candidate_atom_ids":["ATOM-1"],'
        '"reason":"新状态覆盖旧状态","confidence":0.9}'
    )
    assert op is not None
    assert op.op == ReconcileOpType.SUPERSEDE
    assert op.atom_id == "ATOM-1"


def test_parse_reconcile_op_invalid_op():
    assert parse_reconcile_op('{"op":"DELETE"}') is None
    assert parse_reconcile_op("not json") is None


def test_canonical_text_info():
    atom = _atom("content-1", "华为发布旗舰芯片麒麟X1。", "华为发布旗舰芯片麒麟X1")
    text = build_canonical_text(atom)
    assert text.startswith("[信息]")
    assert "华为" in text


def _create_pair(factory):
    repo = SqlAtomRepository(factory)
    old = repo.create_atom(_atom("content-1", "华为旧芯片发布于上月。", "华为发布旧芯片"))
    new = repo.create_atom(_atom("content-2", "华为新芯片今日正式发布。", "华为发布新芯片"))
    return old.atom_id, new.atom_id


def test_apply_supersede(sync_session_factory, two_contents):
    old_id, new_id = _create_pair(sync_session_factory)
    applier = AtomReconcileApplier(sync_session_factory)
    result = applier.apply(
        AtomReconcileOp(op=ReconcileOpType.SUPERSEDE, atom_id=old_id, reason="newer"),
        new_atom_id=new_id,
    )
    assert result["applied"] is True
    session = sync_session_factory()
    try:
        old = session.get(Atom, old_id)
        new = session.get(Atom, new_id)
        assert old.status == AtomStatus.SUPERSEDED.value
        assert old.is_latest is False
        assert old.superseded_by_atom_id == new_id
        assert new.supersedes_atom_id == old_id
        assert new.reconcile_group_id == old.reconcile_group_id
    finally:
        session.close()


def test_apply_merge(sync_session_factory, two_contents):
    old_id, new_id = _create_pair(sync_session_factory)
    applier = AtomReconcileApplier(sync_session_factory)
    applier.apply(
        AtomReconcileOp(op=ReconcileOpType.MERGE, atom_id=old_id, reason="fragment"),
        new_atom_id=new_id,
    )
    session = sync_session_factory()
    try:
        old = session.get(Atom, old_id)
        new = session.get(Atom, new_id)
        assert old.status == AtomStatus.SHADOW.value
        assert new.evidence_count == 2
    finally:
        session.close()


def test_apply_contradict_creates_relation(sync_session_factory, two_contents):
    old_id, new_id = _create_pair(sync_session_factory)
    applier = AtomReconcileApplier(sync_session_factory)
    applier.apply(
        AtomReconcileOp(op=ReconcileOpType.CONTRADICT, atom_id=old_id, reason="conflict"),
        new_atom_id=new_id,
    )
    session = sync_session_factory()
    try:
        rel = session.query(AtomRelation).first()
        assert rel is not None
        assert rel.relation_type == RelationType.CONTRADICTION.value
        old = session.get(Atom, old_id)
        assert "has_contradiction" in (old.quality_flags or [])
    finally:
        session.close()


def test_apply_ignore_shadows_new(sync_session_factory, two_contents):
    _old_id, new_id = _create_pair(sync_session_factory)
    applier = AtomReconcileApplier(sync_session_factory)
    applier.apply(AtomReconcileOp(op=ReconcileOpType.IGNORE, reason="dup"), new_atom_id=new_id)
    session = sync_session_factory()
    try:
        new = session.get(Atom, new_id)
        assert new.status == AtomStatus.SHADOW.value
        assert "reconcile_ignored" in (new.quality_flags or [])
    finally:
        session.close()


def test_apply_add_keeps_active(sync_session_factory, two_contents):
    _old_id, new_id = _create_pair(sync_session_factory)
    applier = AtomReconcileApplier(sync_session_factory)
    applier.apply(AtomReconcileOp(op=ReconcileOpType.ADD, reason="independent"), new_atom_id=new_id)
    session = sync_session_factory()
    try:
        new = session.get(Atom, new_id)
        assert new.status == AtomStatus.ACTIVE.value
        assert new.is_latest is True
    finally:
        session.close()
