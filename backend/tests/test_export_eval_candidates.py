from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.content import Content
from app.models.source import Source, SourceType
from scripts.export_eval_candidates import (
    content_to_eval_record,
    export_eval_candidates,
    interleave_by_source,
)


def _db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


def _source(name: str, url: str = "https://example.com") -> Source:
    return Source(
        name=name,
        type=SourceType.WEBSITE,
        url=url,
        metadata_={"authority_type": "media", "source_stars": 2},
    )


def _content(source: Source, idx: int, **overrides) -> Content:
    created_at = datetime(2026, 7, 1, 12, 0, 0) + timedelta(minutes=idx)
    base = Content(
        source=source,
        external_id=f"story-{idx}",
        title=f"Story {idx}",
        summary=f"Summary {idx}",
        original_url=f"{source.url}/story-{idx}",
        full_content="Full content " * 50,
        content_type="website",
        publish_time=created_at - timedelta(minutes=30),
        fetched_at=created_at,
        created_at=created_at,
        article_score=80 - idx,
        final_score=75 - idx,
        metadata_={
            "fulltext_status": "full",
            "duplicate_group_id": f"group-{idx}",
            "selection_status": "selected",
        },
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_content_to_eval_record_maps_core_fields():
    source = _source("Example", "https://example.com")
    content = _content(source, 1)

    record = content_to_eval_record(content, max_full_content_chars=20)

    assert record["id"] == str(content.id)
    assert record["title"] == "Story 1"
    assert record["label"] == ""
    assert record["article_score"] == 79.0
    assert record["final_score"] == 74.0
    assert record["source_name"] == "Example"
    assert record["source_metadata"]["authority_type"] == "media"
    assert record["metadata"]["fulltext_status"] == "full"
    assert record["duplicate_group_id"] == "group-1"
    assert record["full_content"].endswith("...")


def test_content_to_eval_record_formal_mode_separates_predictions_and_adds_strata():
    source = _source("Example", "https://example.com")
    content = _content(
        source,
        1,
        metadata_={
            "fulltext_status": "full",
            "language": "en",
            "is_paywalled": True,
            "eval_case_type": "paywall",
        },
    )

    record = content_to_eval_record(content, formal_dataset=True)

    assert "article_score" not in record
    assert "final_score" not in record
    assert record["strata"] == {
        "source_type": "website",
        "language": "en",
        "paywall": True,
        "content_length": "medium",
        "case_type": "paywall",
    }


def test_interleave_by_source_round_robins_candidates():
    source_a = _source("A")
    source_b = _source("B", "https://b.example")
    rows = [_content(source_a, 1), _content(source_a, 2), _content(source_b, 3)]

    selected = interleave_by_source(rows, limit=3)

    assert [item.source.name for item in selected] == ["A", "B", "A"]


def test_export_eval_candidates_writes_recent_unlabeled_jsonl(tmp_path):
    db, engine = _db_session()
    try:
        source_a = _source("A")
        source_b = _source("B", "https://b.example")
        db.add_all([source_a, source_b])
        db.flush()
        now = datetime(2026, 7, 10, 12, 0, 0)
        db.add_all(
            [
                _content(source_a, 1, created_at=now - timedelta(days=1)),
                _content(source_a, 2, created_at=now - timedelta(days=2), archived=True),
                _content(source_b, 3, created_at=now - timedelta(days=3)),
                _content(source_b, 4, created_at=now - timedelta(days=40)),
            ]
        )
        db.commit()

        output = tmp_path / "eval_candidates.jsonl"
        records = export_eval_candidates(db, output=output, limit=10, days=30, now=now)

        assert len(records) == 2
        assert {record["source_name"] for record in records} == {"A", "B"}
        assert all(record["label"] == "" for record in records)
        written = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        assert [row["id"] for row in written] == [row["id"] for row in records]
    finally:
        db.close()
        engine.dispose()


def test_export_eval_candidates_expands_window_to_min_records(tmp_path):
    db, engine = _db_session()
    try:
        source_a = _source("A")
        source_b = _source("B", "https://b.example")
        db.add_all([source_a, source_b])
        db.flush()
        now = datetime(2026, 7, 10, 12, 0, 0)
        db.add_all(
            [
                _content(source_a, 1, created_at=now - timedelta(days=1)),
                _content(source_b, 2, created_at=now - timedelta(days=2)),
                _content(source_a, 3, created_at=now - timedelta(days=50)),
            ]
        )
        db.commit()

        diagnostics = {}
        output = tmp_path / "eval_candidates.jsonl"
        records = export_eval_candidates(
            db,
            output=output,
            limit=3,
            days=30,
            min_records=3,
            expand_days_step=30,
            max_days=90,
            now=now,
            diagnostics=diagnostics,
        )

        assert len(records) == 3
        assert diagnostics["requested_days"] == 30
        assert diagnostics["effective_days"] == 60
        assert diagnostics["record_count"] == 3
        written = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        assert len(written) == 3
    finally:
        db.close()
        engine.dispose()
