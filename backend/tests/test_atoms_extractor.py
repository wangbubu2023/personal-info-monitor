"""Tests for atom extraction pipeline."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domains.atoms.atomizer import atomize_content_async
from app.domains.atoms.extractor.llm_extract import parse_llm_atoms
from app.domains.atoms.extractor.sentence_split import split_sentences
from app.domains.atoms.extractor.validate import sentence_in_source
from app.models import Content, Source
from app.models.source import SourceType


@pytest.fixture
def sync_session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'extract.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    try:
        yield factory
    finally:
        engine.dispose()


def test_split_sentences_mixed():
    text = "华为发布了芯片。高盛预计增长5%。Too short.\n\n第二条句子在这里。"
    sentences = split_sentences(text)
    assert "华为发布了芯片。" in sentences
    assert any("高盛" in s for s in sentences)


def test_sentence_in_source_whitespace():
    body = "华为于2026年5月18日在深圳发布了全新旗舰芯片麒麟X1。"
    assert sentence_in_source(body, body)
    assert sentence_in_source("华为于2026年5月18日 在深圳发布了全新旗舰芯片麒麟X1。", body) is True


def test_parse_llm_atoms_info():
    body = "华为于2026年5月18日在深圳发布了全新旗舰芯片麒麟X1。"
    payload = {
        "atoms": [
            {
                "atom_type": "信息",
                "source_sentence": body,
                "atom_source": "财新",
                "domain": "科技",
                "fact_confidence": 0.9,
                "payload": {
                    "when": "2026-05-18",
                    "where": "深圳",
                    "who": [{"name": "华为", "type": "企业"}],
                    "what_type": "产品",
                    "what": "华为发布旗舰芯片麒麟X1",
                    "entities": ["华为", "麒麟X1"],
                    "validity": "中期",
                },
            }
        ]
    }
    atoms = parse_llm_atoms(
        json.dumps(payload, ensure_ascii=False),
        content_id="c1",
        source_url="https://example.com/a",
        full_text=body,
    )
    assert len(atoms) == 1
    assert atoms[0].atom_type.value == "信息"
    assert atoms[0].atom_source == "财新"


@pytest.mark.asyncio
async def test_atomize_content_async_with_mock_llm(monkeypatch, sync_session_factory):
    monkeypatch.setenv("ATOMS_ENABLED", "true")
    session = sync_session_factory()
    try:
        source = Source(
            id="src-1",
            name="财新",
            type=SourceType.RSS,
            url="https://demo.test/feed",
            fetch_interval=60,
        )
        session.add(source)
        session.flush()
        first_sentence = "华为于2026年5月18日在深圳发布了全新旗舰芯片麒麟X1，"
        body = first_sentence + "该芯片采用最新制程，面向旗舰智能手机与数据中心场景。"
        content = Content(
            id="content-1",
            source_id=source.id,
            external_id="ext-1",
            title="华为发布芯片",
            original_url="https://demo.test/a",
            full_content=body,
            content_type="article",
            publish_time=datetime(2026, 5, 20, 9, 30, 0),
            fetched_at=datetime(2026, 5, 20, 9, 30, 0),
        )
        session.add(content)
        session.commit()
    finally:
        session.close()

    llm_json = json.dumps(
        {
            "atoms": [
                {
                    "atom_type": "信息",
                    "source_sentence": first_sentence,
                    "atom_source": "财新",
                    "domain": "科技",
                    "fact_confidence": 0.92,
                    "payload": {
                        "when": "2026-05-18",
                        "where": "深圳",
                        "who": [{"name": "华为", "type": "企业"}],
                        "what_type": "产品",
                        "what": "华为发布旗舰芯片麒麟X1",
                        "entities": ["华为", "麒麟X1"],
                        "validity": "中期",
                    },
                }
            ]
        },
        ensure_ascii=False,
    )

    from types import SimpleNamespace

    mock_runtime = SimpleNamespace(provider="test", model="mock")
    from app.domains.atoms.repository import SqlAtomRepository

    repo = SqlAtomRepository(sync_session_factory)
    with patch("app.domains.atoms.atomizer.SessionLocal", sync_session_factory), patch(
        "app.domains.atoms.atomizer.default_atom_repository",
        return_value=repo,
    ), patch(
        "app.domains.atoms.extractor.pipeline.get_runtime_from_system_settings",
        new=AsyncMock(return_value=mock_runtime),
    ), patch(
        "app.domains.atoms.extractor.pipeline.ModelProviderClient"
    ) as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.generate_text = AsyncMock(return_value=llm_json)
        ok = await atomize_content_async("content-1")
        assert ok is True

    session = sync_session_factory()
    try:
        from app.models.atom import Atom

        rows = session.query(Atom).filter(Atom.content_id == "content-1").all()
        assert len(rows) == 1
        assert rows[0].atom_type == "信息"
    finally:
        session.close()
