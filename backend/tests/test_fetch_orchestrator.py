"""Tests for ``app.domains.fetch.orchestrator.fetch_source_batch``.

Phase 2.5: this entry point is a thin adapter on top of
``CollectorStage.execute``; the tests exercise the contract conversion
(``(list[dict], merged_warning, primary_warning) -> FetchBatch``) and the
source-not-found fallback.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.domains.contracts import FetchBatch, FetchRequest, SourceSnapshot
from app.domains.fetch import fetch_source_batch
from app.models.source import Source


def _snapshot(source_id: str, source_type: str = "rss") -> SourceSnapshot:
    return SourceSnapshot(
        source_id=source_id,
        source_type=source_type,
        name="Test Source",
        primary_url="https://example.com/feed.xml",
    )


def _request(source_id: str, source_type: str = "rss", manual: bool = False) -> FetchRequest:
    return FetchRequest(source=_snapshot(source_id, source_type), manual=manual)


def _fake_db_with(source_row) -> MagicMock:
    db = MagicMock()
    query = MagicMock()
    query.filter.return_value.first.return_value = source_row
    db.query.return_value = query
    return db


def _fake_db_without_source() -> MagicMock:
    db = MagicMock()
    query = MagicMock()
    query.filter.return_value.first.return_value = None
    db.query.return_value = query
    return db


@pytest.mark.asyncio
async def test_returns_empty_batch_with_source_missing_warning_when_row_absent():
    source_id = str(uuid4())
    db = _fake_db_without_source()

    batch = await fetch_source_batch(db, _request(source_id))

    assert isinstance(batch, FetchBatch)
    assert batch.source_id == source_id
    assert batch.items == ()
    assert len(batch.warnings) == 1
    warning = batch.warnings[0]
    assert warning.code == "source_missing"
    assert source_id in warning.message
    assert warning.details["severity"] == "error"


@pytest.mark.asyncio
async def test_maps_raw_dicts_to_raw_items_when_collector_succeeds():
    source_id = str(uuid4())
    source_row = MagicMock(spec=Source)
    db = _fake_db_with(source_row)

    published = datetime(2026, 5, 1, 12, 0, 0)
    raw = [
        {
            "title": "First",
            "url": "https://example.com/1",
            "external_id": "ext-1",
            "content": "body text",
            "publish_time": published,
            "metadata": {"author": "alice"},
        },
        {
            "title": "Second",
            "url": "https://example.com/2",
            "external_id": "ext-2",
            "html": "<p>html body</p>",
            "publish_time": published,
        },
    ]
    with patch(
        "app.pipeline.collector_stage.CollectorStage.execute",
        new=AsyncMock(return_value=(raw, None, None)),
    ):
        batch = await fetch_source_batch(db, _request(source_id))

    assert batch.source_id == source_id
    assert len(batch.items) == 2
    assert batch.warnings == ()

    first, second = batch.items
    assert first.title == "First"
    assert first.url == "https://example.com/1"
    assert first.external_id == "ext-1"
    assert first.content == "body text"
    assert first.html is None
    assert first.publish_time == published
    assert first.metadata == {"author": "alice"}
    assert first.source_id == source_id

    assert second.html == "<p>html body</p>"
    assert second.content is None
    assert second.metadata == {}


@pytest.mark.asyncio
async def test_preserves_primary_warning_triple_as_single_fetch_warning():
    source_id = str(uuid4())
    source_row = MagicMock(spec=Source)
    db = _fake_db_with(source_row)

    raw = [{"title": "x", "url": "https://example.com/x", "external_id": "ext-x"}]
    primary = ("auth_captcha", "error", "登录受阻：检测到验证码/人机挑战")
    merged = "登录受阻：检测到验证码/人机挑战"

    with patch(
        "app.pipeline.collector_stage.CollectorStage.execute",
        new=AsyncMock(return_value=(raw, merged, primary)),
    ):
        batch = await fetch_source_batch(db, _request(source_id))

    assert len(batch.warnings) == 1
    warning = batch.warnings[0]
    assert warning.code == "auth_captcha"
    assert warning.message == primary[2]
    assert warning.details["severity"] == "error"
    assert warning.details["merged"] == merged


@pytest.mark.asyncio
async def test_falls_back_to_merged_warning_when_no_primary_triple():
    source_id = str(uuid4())
    source_row = MagicMock(spec=Source)
    db = _fake_db_with(source_row)

    with patch(
        "app.pipeline.collector_stage.CollectorStage.execute",
        new=AsyncMock(return_value=([], "全文抓取部分成功：尝试 5 篇，成功 2 篇", None)),
    ):
        batch = await fetch_source_batch(db, _request(source_id))

    assert batch.items == ()
    assert len(batch.warnings) == 1
    assert batch.warnings[0].code == "fetch_warning"
    assert "全文抓取部分成功" in batch.warnings[0].message
    assert batch.warnings[0].details["severity"] == "warning"


@pytest.mark.asyncio
async def test_handles_empty_raw_list_with_no_warnings():
    source_id = str(uuid4())
    source_row = MagicMock(spec=Source)
    db = _fake_db_with(source_row)

    with patch(
        "app.pipeline.collector_stage.CollectorStage.execute",
        new=AsyncMock(return_value=([], None, None)),
    ):
        batch = await fetch_source_batch(db, _request(source_id))

    assert batch == FetchBatch(source_id=source_id, items=(), warnings=())


@pytest.mark.asyncio
async def test_invalid_uuid_source_id_falls_back_to_string_query():
    """Non-UUID source_ids (e.g. test fixtures) shouldn't crash the loader."""

    raw_id = "not-a-uuid"
    db = _fake_db_without_source()

    batch = await fetch_source_batch(db, _request(raw_id))

    assert batch.source_id == raw_id
    assert batch.warnings[0].code == "source_missing"
