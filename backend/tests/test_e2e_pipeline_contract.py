from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Content, Source
from app.models.source import SourceType
from app.domains.fetch.coordinator import run_fetch_pipeline
from app.utils.datetime import utcnow_naive


def _raw_feed_item() -> dict:
    return {
        "external_id": "fixture-item-1",
        "title": "Fixture feed item",
        "content": "A stable contract-test article body. " * 20,
        "url": "https://example.com/news/fixture-item-1",
        "publish_time": utcnow_naive() - timedelta(minutes=5),
        "metadata": {"source_kind": "fixture_feed"},
    }


def _duplicate_raw_feed_item(item_id: str) -> dict:
    return {
        "external_id": f"fixture-item-{item_id}",
        "title": "Same Feed Article About Storage Economics",
        "content": "A duplicated RSS article body with enough text. " * 20,
        "url": f"https://example.com/news/fixture-item-{item_id}",
        "publish_time": utcnow_naive() - timedelta(minutes=5),
        "metadata": {"source_kind": "fixture_feed"},
    }


@pytest.mark.asyncio
async def test_fetch_pipeline_contract_saves_once_then_dedupes_second_round():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        source = Source(
            name="Fixture Feed",
            type=SourceType.RSS,
            url="https://example.com/feed.xml",
            fetch_interval=60,
            enabled=True,
            metadata_={},
        )
        db.add(source)
        db.commit()
        db.refresh(source)

        async def _collect(*_args, **_kwargs):
            return ([_raw_feed_item()], None, None)

        with patch(
            "app.domains.fetch.collector_stage.CollectorStage.execute",
            new=AsyncMock(side_effect=_collect),
        ) as collect_mock:
            first = await run_fetch_pipeline(db, source)
            second = await run_fetch_pipeline(db, source)

        assert first["status"] == "success"
        assert first["count"] == 1
        assert first["saved"] == 1
        assert len(first["new_content_ids"]) == 1
        assert source.last_content_id == "fixture-item-1"

        assert second["status"] == "success"
        assert second["message"] == "All content up to date"
        assert second["count"] == 0
        assert source.error_count == 0
        assert collect_mock.await_count == 2

        rows = db.execute(select(Content)).scalars().all()
        assert len(rows) == 1
        assert rows[0].external_id == "fixture-item-1"
        assert rows[0].metadata_["source_kind"] == "fixture_feed"
    finally:
        db.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_fetch_pipeline_marks_same_title_group_duplicate_rows():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        source = Source(
            name="Fixture Feed",
            type=SourceType.RSS,
            url="https://example.com/feed.xml",
            fetch_interval=60,
            enabled=True,
            metadata_={},
        )
        db.add(source)
        db.commit()
        db.refresh(source)

        async def _collect(*_args, **_kwargs):
            return ([_duplicate_raw_feed_item("1"), _duplicate_raw_feed_item("2")], None, None)

        with patch(
            "app.domains.fetch.collector_stage.CollectorStage.execute",
            new=AsyncMock(side_effect=_collect),
        ):
            result = await run_fetch_pipeline(db, source)

        assert result["status"] == "success"
        assert result["saved"] == 2

        rows = db.execute(select(Content).order_by(Content.fetched_at, Content.id)).scalars().all()
        assert len(rows) == 2
        canonical = next(row for row in rows if not row.is_duplicate)
        duplicate = next(row for row in rows if row.is_duplicate)
        assert duplicate.duplicate_of == str(canonical.id)
        assert duplicate.metadata_["duplicate_of"] == str(canonical.id)
        assert duplicate.metadata_["is_duplicate"] is True
        assert canonical.metadata_["is_duplicate"] is False
        assert duplicate.metadata_["duplicate_group_id"] == canonical.metadata_["duplicate_group_id"]
    finally:
        db.close()
        engine.dispose()
