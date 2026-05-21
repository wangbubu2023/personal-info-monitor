"""Cross-article atom relations repository tests (P2)."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domains.atoms.relation_infer.worker import infer_relations
from app.domains.atoms.relation_infer.candidates import (
    entities_overlap,
    extract_entity_names,
    find_candidates,
    time_compatible,
)
from app.domains.atoms.relation_infer.llm_judge import parse_relation_judgment
from app.domains.atoms.types import RelationCreate
from app.domains.atoms.relations_repository import (
    CONFIDENCE_BOOST,
    SqlAtomRelationRepository,
)
from app.domains.atoms.repository import SqlAtomRepository
from app.domains.atoms.types import RelationCreate, RelationUpdate
from app.domains.atoms.vocab import RelationDirection, RelationType
from app.models import Content, Source
from app.models.source import SourceType
from tests.test_atoms_repository import _info_atom, seeded_content  # noqa: F401 — seeded_content fixture


@pytest.fixture
def sync_session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'relations.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def second_content(sync_session_factory, seeded_content):  # noqa: ARG001 — ensures src-1 exists
    session = sync_session_factory()
    try:
        source = session.get(Source, "src-1")
        content = Content(
            id="content-2",
            source_id=source.id,
            external_id="ext-2",
            title="Second article",
            original_url="https://demo.test/articles/second",
            full_content="华为麒麟X1芯片于5月18日在深圳正式发布。",
            content_type="article",
            publish_time=datetime(2026, 5, 19, 10, 0, 0),
            fetched_at=datetime(2026, 5, 19, 10, 0, 0),
        )
        session.add(content)
        session.commit()
        return content.id
    finally:
        session.close()


def _info_atom_sentence(content_id: str, source_sentence: str):
    atom = _info_atom(content_id)
    return atom.model_copy(update={"source_sentence": source_sentence})


@pytest.fixture
def two_atoms(sync_session_factory, seeded_content, second_content):
    atom_repo = SqlAtomRepository(sync_session_factory)
    a = atom_repo.create_atom(_info_atom(seeded_content))
    b = atom_repo.create_atom(
        _info_atom_sentence(
            second_content,
            "华为麒麟X1芯片于5月18日在深圳正式发布。",
        )
    )
    return a.atom_id, b.atom_id


def _corroboration(atom_a: str, atom_b: str, *, verified: bool = False) -> RelationCreate:
    return RelationCreate(
        atom_a=atom_a,
        atom_b=atom_b,
        relation_type=RelationType.CORROBORATION,
        direction=RelationDirection.BIDIRECTIONAL,
        fact_confidence=0.85,
        verified=verified,
    )


def test_upsert_creates_relation(sync_session_factory, two_atoms):
    rel_repo = SqlAtomRelationRepository(sync_session_factory)
    atom_a, atom_b = two_atoms
    created = rel_repo.upsert_relation(_corroboration(atom_a, atom_b))
    assert created.rel_id.startswith("REL-")
    assert created.relation_type == RelationType.CORROBORATION
    assert created.verified is False


def test_upsert_updates_unverified(sync_session_factory, two_atoms):
    rel_repo = SqlAtomRelationRepository(sync_session_factory)
    atom_a, atom_b = two_atoms
    first = rel_repo.upsert_relation(_corroboration(atom_a, atom_b))
    second = rel_repo.upsert_relation(
        RelationCreate(
            atom_a=atom_a,
            atom_b=atom_b,
            relation_type=RelationType.CONTRADICTION,
            direction=RelationDirection.A_TO_B,
            fact_confidence=0.6,
        )
    )
    assert first.rel_id == second.rel_id
    assert second.relation_type == RelationType.CONTRADICTION
    assert second.fact_confidence == 0.6


def test_upsert_skips_verified(sync_session_factory, two_atoms):
    rel_repo = SqlAtomRelationRepository(sync_session_factory)
    atom_a, atom_b = two_atoms
    verified = rel_repo.upsert_relation(_corroboration(atom_a, atom_b, verified=True))
    overwritten = rel_repo.upsert_relation(
        RelationCreate(
            atom_a=atom_a,
            atom_b=atom_b,
            relation_type=RelationType.CONTRADICTION,
            direction=RelationDirection.A_TO_B,
            fact_confidence=0.1,
        )
    )
    assert overwritten.rel_id == verified.rel_id
    assert overwritten.relation_type == RelationType.CORROBORATION
    assert overwritten.verified is True
    assert overwritten.fact_confidence == 0.85


def test_list_relations_global_filter(sync_session_factory, two_atoms):
    rel_repo = SqlAtomRelationRepository(sync_session_factory)
    atom_a, atom_b = two_atoms
    rel_repo.upsert_relation(_corroboration(atom_a, atom_b))

    from app.domains.atoms.relations_repository import RelationListFilters

    items, total = rel_repo.list_relations(RelationListFilters(atom_id=atom_a))
    assert total == 1
    assert items[0].atom_a == atom_a


def test_list_relations_for_atom(sync_session_factory, two_atoms):
    rel_repo = SqlAtomRelationRepository(sync_session_factory)
    atom_a, atom_b = two_atoms
    rel_repo.upsert_relation(_corroboration(atom_a, atom_b))
    for atom_id, expected_len in ((atom_a, 1), (atom_b, 1)):
        rows = rel_repo.list_relations_for_atom(atom_id)
        assert len(rows) == expected_len
        assert rows[0].rel_id.startswith("REL-")


def test_delete_relation(sync_session_factory, two_atoms):
    rel_repo = SqlAtomRelationRepository(sync_session_factory)
    atom_a, atom_b = two_atoms
    created = rel_repo.upsert_relation(_corroboration(atom_a, atom_b))
    assert rel_repo.delete_relation(created.rel_id) is True
    assert rel_repo.get_relation(created.rel_id) is None
    assert rel_repo.delete_relation("REL-missing") is False


def test_apply_verified_corroboration_boosts_atoms(sync_session_factory, two_atoms):
    rel_repo = SqlAtomRelationRepository(sync_session_factory)
    atom_repo = SqlAtomRepository(sync_session_factory)
    atom_a, atom_b = two_atoms
    before_a = atom_repo.get_atom(atom_a)
    before_b = atom_repo.get_atom(atom_b)
    assert before_a is not None and before_b is not None

    created = rel_repo.upsert_relation(_corroboration(atom_a, atom_b))
    rel_repo.apply_verified_corroboration(created.rel_id)

    after_a = atom_repo.get_atom(atom_a)
    after_b = atom_repo.get_atom(atom_b)
    assert after_a is not None and after_b is not None
    assert after_a.fact_confidence == pytest.approx(
        min(1.0, before_a.fact_confidence + CONFIDENCE_BOOST)
    )
    assert after_b.fact_confidence == pytest.approx(
        min(1.0, before_b.fact_confidence + CONFIDENCE_BOOST)
    )

    updated_rel = rel_repo.get_relation(created.rel_id)
    assert updated_rel is not None
    assert updated_rel.verified is True


def test_extract_entity_names_info():
    names = extract_entity_names(
        "信息",
        {"entities": ["华为", "麒麟X1"], "who": [{"name": "华为", "type": "企业"}]},
    )
    assert "华为" in names
    assert "麒麟X1" in names


def test_entities_overlap():
    assert entities_overlap({"华为"}, {"华为", "苹果"}) is True
    assert entities_overlap({"华为"}, {"苹果"}) is False


def test_time_compatible_same_period():
    assert time_compatible(
        left_type="数据",
        left_payload={"period": "2026Q1"},
        right_type="数据",
        right_payload={"period": "2026Q1"},
    )


def test_find_candidates_cross_content(sync_session_factory, two_atoms):
    atom_repo = SqlAtomRepository(sync_session_factory)
    atom_a, _atom_b = two_atoms
    atom = atom_repo.get_atom(atom_a)
    assert atom is not None

    session = sync_session_factory()
    try:
        candidates = find_candidates(session, atom)
    finally:
        session.close()

    assert len(candidates) >= 1
    assert all(c.content_id != atom.content_id for c in candidates)


def test_parse_relation_judgment_corroboration(sync_session_factory, two_atoms):
    atom_a, atom_b = two_atoms
    raw = (
        '{"relation_type":"印证","direction":"双向","fact_confidence":0.88,"reason":"同一事件"}'
    )
    rel = parse_relation_judgment(raw, atom_a=atom_a, atom_b=atom_b)
    assert rel is not None
    assert rel.relation_type.value == "印证"
    assert rel.direction.value == "双向"


@pytest.mark.asyncio
async def test_infer_relations_mock_judge(monkeypatch, sync_session_factory, two_atoms):
    monkeypatch.setenv("ATOMS_ENABLED", "true")
    monkeypatch.setenv("ATOMS_RELATIONS_ENABLED", "true")
    monkeypatch.setattr("app.database.SessionLocal", sync_session_factory)
    atom_a, atom_b = two_atoms

    async def fake_judge(atom, candidate):
        return RelationCreate(
            atom_a=atom.atom_id,
            atom_b=candidate.atom_id,
            relation_type=RelationType.CORROBORATION,
            direction=RelationDirection.BIDIRECTIONAL,
            fact_confidence=0.9,
        )

    monkeypatch.setattr(
        "app.domains.atoms.relation_infer.worker.judge_relation_pair",
        fake_judge,
    )

    created = await infer_relations(atom_a)
    assert created >= 1

    rel_repo = SqlAtomRelationRepository(sync_session_factory)
    rels = rel_repo.list_relations_for_atom(atom_a)
    assert len(rels) >= 1
    assert rels[0].relation_type == RelationType.CORROBORATION


def test_parse_relation_judgment_null(sync_session_factory, two_atoms):
    atom_a, atom_b = two_atoms
    assert parse_relation_judgment('{"relation_type":null}', atom_a=atom_a, atom_b=atom_b) is None


def test_update_relation_verify_triggers_boost(sync_session_factory, two_atoms):
    rel_repo = SqlAtomRelationRepository(sync_session_factory)
    atom_repo = SqlAtomRepository(sync_session_factory)
    atom_a, atom_b = two_atoms
    before = atom_repo.get_atom(atom_a)
    assert before is not None

    created = rel_repo.upsert_relation(_corroboration(atom_a, atom_b))
    rel_repo.update_relation(created.rel_id, RelationUpdate(verified=True))

    after = atom_repo.get_atom(atom_a)
    assert after is not None
    assert after.fact_confidence == pytest.approx(
        min(1.0, before.fact_confidence + CONFIDENCE_BOOST)
    )
