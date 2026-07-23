from __future__ import annotations

from datetime import timedelta

from app.models.postprocess_job import PostprocessJob
from app.platform.workers.postprocess_jobs import (
    claim_postprocess_job,
    due_postprocess_jobs,
    ensure_postprocess_job,
    ensure_postprocess_jobs,
    mark_postprocess_job_failed,
    mark_postprocess_job_succeeded,
    postprocess_completion_rate,
    recover_stale_postprocess_jobs,
)
from app.utils.datetime import utcnow_naive


def test_postprocess_job_lifecycle(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import Base
    import app.platform.workers.postprocess_jobs as jobs

    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(jobs, "SessionLocal", session_factory)

    ensure_postprocess_job("content-1", "fetch-1")
    assert due_postprocess_jobs() == [("content-1", "fetch-1")]

    assert claim_postprocess_job("content-1", "fetch-1") is True
    assert due_postprocess_jobs() == []

    status = mark_postprocess_job_failed("content-1", "fetch-1", TimeoutError("temporary"))
    assert status == "pending"

    db = session_factory()
    try:
        job = db.query(PostprocessJob).one()
        assert job.last_error.startswith("[timeout]")
        assert "抓取超时" in job.last_error
    finally:
        db.close()

    db = session_factory()
    try:
        job = db.query(PostprocessJob).one()
        job.run_after = utcnow_naive() - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    assert claim_postprocess_job("content-1", "fetch-1") is True
    mark_postprocess_job_succeeded("content-1", "fetch-1")
    assert claim_postprocess_job("content-1", "fetch-1") is False
    # Replaying the same content fingerprint + pipeline job must not revive a
    # completed side effect.
    assert ensure_postprocess_jobs([("content-1", "fetch-1")]) == 0
    assert due_postprocess_jobs() == []

    metrics = postprocess_completion_rate()
    assert metrics["total"] == 1
    assert metrics["succeeded"] == 1
    assert metrics["completion_rate"] == 1.0


def test_postprocess_source_batch_uses_one_commit(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker

    import app.platform.workers.postprocess_jobs as jobs
    from app.database import Base

    commit_calls = 0

    class CountingSession(Session):

        def commit(self):
            nonlocal commit_calls
            commit_calls += 1
            return super().commit()

    engine = create_engine(f"sqlite:///{tmp_path / 'batch-jobs.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, class_=CountingSession)
    monkeypatch.setattr(jobs, "SessionLocal", session_factory)

    batch = [(f"content-{index}", "fetch-1") for index in range(20)]
    assert ensure_postprocess_jobs(batch) == 20
    assert commit_calls == 1

    # Re-enqueueing active rows performs one batched read and no write commit.
    assert ensure_postprocess_jobs(batch) == 0
    assert commit_calls == 1

    with session_factory() as db:
        assert db.query(PostprocessJob).count() == 20


def test_stale_running_postprocess_job_is_recovered(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import Base
    import app.platform.workers.postprocess_jobs as jobs

    engine = create_engine(f"sqlite:///{tmp_path / 'stale-jobs.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(jobs, "SessionLocal", session_factory)

    ensure_postprocess_job("content-stale", "finish")
    assert claim_postprocess_job("content-stale", "finish") is True

    db = session_factory()
    try:
        job = db.query(PostprocessJob).one()
        job.locked_at = utcnow_naive() - timedelta(minutes=15)
        job.started_at = job.locked_at
        db.commit()
    finally:
        db.close()

    assert recover_stale_postprocess_jobs() == 1
    assert due_postprocess_jobs() == [("content-stale", "finish")]


def test_stale_running_job_at_retry_cap_is_not_reclaimed(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import Base
    import app.platform.workers.postprocess_jobs as jobs

    engine = create_engine(f"sqlite:///{tmp_path / 'retry-cap.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(jobs, "SessionLocal", session_factory)

    ensure_postprocess_job("content-capped", "finish")
    db = session_factory()
    try:
        job = db.query(PostprocessJob).one()
        job.status = "running"
        job.attempts = job.max_attempts
        job.locked_at = utcnow_naive() - timedelta(minutes=15)
        job.started_at = job.locked_at
        db.commit()
    finally:
        db.close()

    assert claim_postprocess_job("content-capped", "finish") is False
    db = session_factory()
    try:
        job = db.query(PostprocessJob).one()
        assert job.status == "dead"
        assert job.attempts == job.max_attempts
    finally:
        db.close()
