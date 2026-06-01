"""Tests for L3 event clustering and L5 entity layer."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domains.atoms.entities.extract import extract_entity_mentions
from app.domains.atoms.entities.repository import SqlEntityRepository
from app.domains.atoms.events.clustering import assign_atom_to_cluster
from app.domains.atoms.events.repository import SqlEventRepository
from app.domains.atoms.repository import SqlAtomRepository
from app.domains.atoms.types import AtomCreate, InfoAtomPayload
from app.domains.atoms.vocab import AtomType, Domain, SubjectType, Validity, WhatType
from app.models import Content, Source
from app.models.source import SourceType


@pytest.fixture
def sync_session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ke.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def contents(sync_session_factory):
    session = sync_session_factory()
    try:
        source = Source(
            id="src-1", name="Demo", type=SourceType.RSS,
            url="https://demo.test/feed", fetch_interval=60,
        )
        session.add(source)
        session.flush()
        for cid in ("content-1", "content-2"):
            session.add(
                Content(
                    id=cid, source_id=source.id, external_id=f"ext-{cid}", title="t",
                    original_url=f"https://demo.test/{cid}", full_content="正文",
                    content_type="article",
                    publish_time=datetime(2026, 5, 20, 9, 30, 0),
                    fetched_at=datetime(2026, 5, 20, 9, 30, 0),
                )
            )
        session.commit()
    finally:
        session.close()


def _atom(content_id: str, sentence: str, who: str, entities: list[str]) -> AtomCreate:
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
        canonical_text=f"[信息] {who} {sentence}",
        payload=InfoAtomPayload(
            who=[{"name": who, "type": SubjectType.COMPANY}],
            what_type=WhatType.PRODUCT,
            what=sentence,
            entities=entities,
            validity=Validity.MEDIUM,
        ),
    )


def test_extract_entity_mentions():
    atom = _atom("content-1", "华为发布芯片", "华为", ["华为", "麒麟X1"])
    repo_atom = atom.model_copy()
    # build an AtomRecord-like object via repository roundtrip is overkill; use payload
    from app.domains.atoms.types import AtomRecord

    record = AtomRecord(
        atom_id="ATOM-x", content_id="content-1", atom_type=AtomType.INFO, domain=Domain.TECH,
        source_sentence="华为发布芯片", source_url="u", atom_source="财新",
        payload=repo_atom.payload.model_dump(mode="json"), verified=False,
        source_credibility=0.9, fact_confidence=0.95, schema_version=2,
        created_at=datetime(2026, 5, 20), updated_at=datetime(2026, 5, 20),
    )
    mentions = extract_entity_mentions(record)
    names = {m.name for m in mentions}
    assert "华为" in names
    assert "麒麟X1" in names


def test_entity_link_dedupes_alias(sync_session_factory, contents):
    atom_repo = SqlAtomRepository(sync_session_factory)
    a1 = atom_repo.create_atom(_atom("content-1", "华为发布旗舰芯片麒麟X1。", "华为", ["华为", "麒麟X1"]))
    a2 = atom_repo.create_atom(_atom("content-2", "华为公布新一代麒麟芯片细节。", "华为", ["华为"]))

    ent_repo = SqlEntityRepository(sync_session_factory)
    ent_repo.link_atom_entities(a1)
    ent_repo.link_atom_entities(a2)

    entities = ent_repo.list_entities()
    huawei = [e for e in entities if e["canonical_name"] == "华为"]
    assert len(huawei) == 1
    assert huawei[0]["atom_count"] == 2


def test_event_clustering_groups_overlapping_entities(sync_session_factory, contents):
    atom_repo = SqlAtomRepository(sync_session_factory)
    a1 = atom_repo.create_atom(_atom("content-1", "华为发布旗舰芯片麒麟X1。", "华为", ["华为", "麒麟X1"]))
    a2 = atom_repo.create_atom(_atom("content-2", "华为麒麟X1芯片量产进展披露。", "华为", ["华为", "麒麟X1"]))

    session = sync_session_factory()
    try:
        e1 = assign_atom_to_cluster(session, a1)
        e2 = assign_atom_to_cluster(session, a2)
    finally:
        session.close()
    assert e1 is not None
    assert e1 == e2

    event_repo = SqlEventRepository(sync_session_factory)
    assert set(event_repo.list_atom_ids(e1)) == {a1.atom_id, a2.atom_id}


def test_event_summary_and_listing(sync_session_factory, contents):
    atom_repo = SqlAtomRepository(sync_session_factory)
    a1 = atom_repo.create_atom(_atom("content-1", "华为发布旗舰芯片麒麟X1。", "华为", ["华为"]))
    session = sync_session_factory()
    try:
        event_id = assign_atom_to_cluster(session, a1)
    finally:
        session.close()

    event_repo = SqlEventRepository(sync_session_factory)
    event_repo.add_summary(event_id, summary="华为芯片事件摘要", source_atom_ids=[a1.atom_id])
    clusters = event_repo.list_clusters()
    assert len(clusters) == 1
    assert clusters[0]["canonical_summary"] == "华为芯片事件摘要"
    assert clusters[0]["atom_count"] == 1
