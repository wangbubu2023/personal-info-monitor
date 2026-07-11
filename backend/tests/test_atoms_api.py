"""HTTP integration tests for atoms and atom-relations APIs."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domains.atoms.repository import SqlAtomRepository
from app.features import atoms_product_enabled
from app.models import Content, Source
from app.models.source import SourceType
from tests.test_atoms_repository import _info_atom


pytestmark = pytest.mark.skipif(
    not atoms_product_enabled(),
    reason="Atoms product surface is frozen on this branch",
)


def _info_atom_sentence(content_id: str, source_sentence: str):
    atom = _info_atom(content_id)
    return atom.model_copy(update={"source_sentence": source_sentence})


@pytest.fixture
def atoms_api_env(client, tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'atoms_api.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    monkeypatch.setattr("app.database.SessionLocal", factory)
    monkeypatch.setenv("ATOMS_ENABLED", "true")
    monkeypatch.setenv("ATOMS_RELATIONS_ENABLED", "true")
    return client, factory


@pytest.fixture
def seeded_atoms(atoms_api_env):
    _client, factory = atoms_api_env
    session = factory()
    try:
        source = Source(
            id="src-api-1",
            name="Demo",
            type=SourceType.RSS,
            url="https://demo.test/feed",
            fetch_interval=60,
        )
        session.add(source)
        session.flush()
        content_id = "content-api-1"
        content = Content(
            id=content_id,
            source_id=source.id,
            external_id="ext-api-1",
            title="Atoms API test",
            original_url="https://demo.test/articles/api",
            full_content="华为于2026年5月18日在深圳发布了全新旗舰芯片麒麟X1。",
            content_type="article",
            publish_time=datetime(2026, 5, 20, 9, 30, 0),
            fetched_at=datetime(2026, 5, 20, 9, 30, 0),
        )
        session.add(content)
        session.commit()
    finally:
        session.close()

    repo = SqlAtomRepository(factory)
    created = repo.create_atom(_info_atom(content_id))
    return created.atom_id, content_id


@pytest.mark.asyncio
async def test_atoms_list_requires_flag(client, monkeypatch):
    monkeypatch.delenv("ATOMS_ENABLED", raising=False)
    response = await client.get("/api/atoms")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_atoms_list_and_get(atoms_api_env, seeded_atoms):
    client, _factory = atoms_api_env
    atom_id, _content_id = seeded_atoms

    list_resp = await client.get("/api/atoms")
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["total"] >= 1
    assert any(item["atom_id"] == atom_id for item in body["items"])

    get_resp = await client.get(f"/api/atoms/{atom_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["atom_id"] == atom_id


@pytest.mark.asyncio
async def test_relations_crud(atoms_api_env, seeded_atoms):
    client, factory = atoms_api_env
    atom_a, content_id = seeded_atoms

    session = factory()
    try:
        source = session.get(Source, "src-api-1")
        content = Content(
            id="content-api-2",
            source_id=source.id,
            external_id="ext-api-2",
            title="Second",
            original_url="https://demo.test/2",
            full_content="华为麒麟X1芯片于5月18日在深圳正式发布。",
            content_type="article",
            publish_time=datetime(2026, 5, 19, 10, 0, 0),
            fetched_at=datetime(2026, 5, 19, 10, 0, 0),
        )
        session.add(content)
        session.commit()
    finally:
        session.close()

    atom_repo = SqlAtomRepository(factory)
    atom_b = atom_repo.create_atom(
        _info_atom_sentence(
            "content-api-2",
            "华为麒麟X1芯片于5月18日在深圳正式发布。",
        )
    ).atom_id

    create_resp = await client.post(
        "/api/atom-relations",
        json={
            "atom_a": atom_a,
            "atom_b": atom_b,
            "relation_type": "印证",
            "direction": "双向",
            "fact_confidence": 0.85,
        },
    )
    assert create_resp.status_code == 201
    rel_id = create_resp.json()["rel_id"]

    list_resp = await client.get("/api/atoms/relations", params={"atom_id": atom_a})
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] >= 1

    per_atom_resp = await client.get(f"/api/atoms/{atom_a}/relations")
    assert per_atom_resp.status_code == 200
    assert len(per_atom_resp.json()["items"]) >= 1

    verify_resp = await client.post(f"/api/atom-relations/{rel_id}/verify")
    assert verify_resp.status_code == 200
    assert verify_resp.json()["verified"] is True

    delete_resp = await client.delete(f"/api/atom-relations/{rel_id}")
    assert delete_resp.status_code == 204


@pytest.mark.asyncio
async def test_relations_disabled_returns_404(atoms_api_env, monkeypatch):
    client, _factory = atoms_api_env
    monkeypatch.setenv("ATOMS_RELATIONS_ENABLED", "false")
    response = await client.get("/api/atoms/relations")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_relations_reconcile_job(atoms_api_env, seeded_atoms, monkeypatch):
    client, _factory = atoms_api_env
    _atom_id, _content_id = seeded_atoms

    async def _fake_infer(atom_id: str) -> int:
        return 0

    monkeypatch.setattr(
        "app.domains.atoms.reconcile.infer_relations",
        _fake_infer,
    )

    start_resp = await client.post(
        "/api/atoms/relations/reconcile",
        json={"limit": 10, "dry_run": True},
    )
    assert start_resp.status_code == 202
    job_id = start_resp.json()["job_id"]

    import asyncio

    for _ in range(50):
        status_resp = await client.get(f"/api/atoms/relations/reconcile/{job_id}")
        assert status_resp.status_code == 200
        if status_resp.json()["status"] in {"done", "failed"}:
            break
        await asyncio.sleep(0.05)
    assert status_resp.json()["status"] == "done"
