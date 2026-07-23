from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Content, FetchJob, Source


@pytest.fixture
def m0_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def _content(source_id: str | None, external_id: str, *, body: str = "body", summary: str = "summary") -> Content:
    return Content(
        source_id=source_id,
        external_id=external_id,
        title=f"Title {external_id}",
        summary=summary,
        full_content=body,
        original_url=f"https://example.com/{external_id}",
        content_type="rss",
        publish_time=datetime(2026, 7, 22, 12, 0),
        metadata_={"fulltext_status": "full", "fetch_acceptance": "accepted"},
    )


def test_storage_result_conserves_mixed_batch_and_replay(m0_session_factory):
    from app.domains.ingest.storage import StorageStage

    with m0_session_factory() as db:
        source = Source(name="M0", type="rss", url="https://example.com/feed")
        db.add(source)
        db.flush()
        source_id = str(source.id)
        db.add_all(
            [
                _content(source_id, "updated", body="old body"),
                _content(source_id, "same-1"),
                _content(source_id, "same-2"),
            ]
        )
        db.commit()

        batch = [
            *[_content(source_id, f"new-{idx}") for idx in range(6)],
            _content(source_id, "updated", body="new substantive body"),
            _content(source_id, "same-1"),
            _content(source_id, "same-2"),
            _content(None, "broken"),
        ]
        result = StorageStage.execute(db, batch)
        db.commit()

        assert result.requested_count == 10
        assert result.saved_count == 6
        assert result.updated_count == 1
        assert result.unchanged_duplicate_count == 2
        assert result.failed_count == 1
        assert result.outcome.value == "partial_failure"
        assert len(result.postprocess_candidates) == 7
        assert result.failed_items[0].failure_class == "schema"
        result.assert_conservation()

        replay = StorageStage.execute(db, [_content(source_id, "updated", body="new substantive body")])
        assert replay.unchanged_duplicate_count == 1
        assert replay.postprocess_candidates == []


@pytest.mark.asyncio
async def test_fetch_job_is_durable_when_queue_full_and_deduplicates(monkeypatch, m0_session_factory):
    import app.platform.workers.fetch_jobs as jobs
    from app.platform.workers.queue import BoundedTaskQueue

    monkeypatch.setattr(jobs, "SessionLocal", m0_session_factory)
    with m0_session_factory() as db:
        source = Source(name="Fetch", type="rss", url="https://example.com/fetch")
        db.add(source)
        db.commit()
        source_id = str(source.id)

    queue = BoundedTaskQueue(fetch_maxsize=1, process_maxsize=1)
    queue._fetch_queue.put_nowait(("occupied", "other", False))
    due = datetime(2026, 7, 22, 12, 0)
    first = await queue.enqueue_fetch(source_id, fetch_kind="manual", due_window=due)
    second = await queue.enqueue_fetch(source_id, fetch_kind="manual", due_window=due)

    assert first.persisted and not first.enqueued and first.reason == "execution_cache_full"
    assert second.persisted and second.duplicate
    assert second.job_id == first.job_id
    with m0_session_factory() as db:
        rows = db.query(FetchJob).all()
        assert len(rows) == 1
        assert rows[0].state == "pending"
        assert rows[0].enqueued_at is None


def test_web_bootstrap_code_replay_rotation_and_revocation(monkeypatch, m0_session_factory):
    import app.platform.auth.web_session as sessions

    monkeypatch.setattr(sessions, "SessionLocal", m0_session_factory)
    code = sessions.issue_bootstrap_code(actor="test-operator")
    issued = sessions.exchange_bootstrap_code(code)

    assert issued is not None
    assert sessions.exchange_bootstrap_code(code) is None
    assert sessions.validate_web_session(issued.token) == "test-operator"

    rotated = sessions.rotate_web_session(issued.token)
    assert rotated is not None
    assert sessions.validate_web_session(issued.token) is None
    assert sessions.validate_web_session(rotated.token) == "test-operator"
    assert sessions.revoke_web_session(rotated.token) is True
    assert sessions.validate_web_session(rotated.token) is None


def test_bootstrap_eval_gate_fails_closed_when_real_data_missing(tmp_path):
    from scripts.check_bootstrap_eval import check_bootstrap_eval

    result = check_bootstrap_eval(
        tmp_path / "core.jsonl",
        tmp_path / "core-manifest.json",
        tmp_path / "event.jsonl",
        tmp_path / "event-manifest.json",
    )
    assert result["ok"] is False
    assert any("not installed" in error for error in result["errors"])


def test_bootstrap_eval_rejects_hash_prediction_and_non_human_labels(tmp_path):
    from scripts.check_bootstrap_eval import _manifest_errors, _prediction_errors

    dataset = tmp_path / "core.jsonl"
    dataset.write_text('{"id":"one"}\n', encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"dataset_tier":"bootstrap","release_scope":"m0_m1_infrastructure_only",'
        '"dataset_sha256":"wrong","git_commit":"abc","sampling_interval":"2026-07",'
        '"deidentification":"redacted","annotation_policy":"manual","annotators":["owner"],'
        '"limitations":"bootstrap only"}',
        encoding="utf-8",
    )

    assert "dataset_sha256 mismatch" in " ".join(_manifest_errors(manifest, dataset, kind="core"))
    errors = _prediction_errors(
        [{"article_score": 99, "label_source": "pipeline"}],
        kind="core",
    )
    assert any("prefilled prediction" in error for error in errors)
    assert any("human-reviewed" in error for error in errors)
