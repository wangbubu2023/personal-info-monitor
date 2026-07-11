from __future__ import annotations

from datetime import timedelta

from app.models.postprocess_job import PostprocessJob
from app.platform.workers.postprocess_jobs import (
    claim_postprocess_job,
    due_postprocess_jobs,
    ensure_postprocess_job,
    mark_postprocess_job_failed,
    mark_postprocess_job_succeeded,
    postprocess_completion_rate,
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

    status = mark_postprocess_job_failed("content-1", "fetch-1", RuntimeError("temporary"))
    assert status == "pending"

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

    metrics = postprocess_completion_rate()
    assert metrics["total"] == 1
    assert metrics["succeeded"] == 1
    assert metrics["completion_rate"] == 1.0
