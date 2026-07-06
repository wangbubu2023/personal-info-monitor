"""Weekly health report aggregation + rendering tests."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.database import Base
from app.domains.system.weekly_report import (
    _load_eval_history_summary,
    _render_weekly_report_html,
    build_weekly_health_report,
)
from app.models import Content, Source
from app.models.source import SourceType
from app.models.source_fetch_log import SourceFetchLog
from app.utils.datetime import utcnow_naive


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'weekly_report.db'}", future=True, poolclass=NullPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _make_source(db, *, name: str, **kwargs) -> Source:
    source = Source(name=name, url=f"https://example.com/{name}", type=SourceType.RSS, **kwargs)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def test_build_weekly_health_report_aggregates_fetch_and_sessions(session_factory):
    db = session_factory()
    now = utcnow_naive()

    healthy = _make_source(db, name="healthy")
    failing = _make_source(
        db,
        name="failing",
        session_health_status="expired",
        session_health_reason="cookie_expired",
    )
    disabled = _make_source(db, name="disabled", enabled=False)
    cooled = _make_source(db, name="cooled", fetch_cooldown_until=now + timedelta(hours=1))
    assert disabled is not None and cooled is not None

    db.add_all(
        [
            SourceFetchLog(
                source_id=healthy.id,
                attempted_at=now - timedelta(days=1),
                outcome="success",
                saved_count=3,
                fulltext_ok=2,
                fulltext_total=3,
            ),
            SourceFetchLog(
                source_id=failing.id,
                attempted_at=now - timedelta(days=2),
                outcome="failure",
                failure_code="http_429",
            ),
            SourceFetchLog(
                source_id=failing.id,
                attempted_at=now - timedelta(days=3),
                outcome="failure",
                failure_code="http_429",
            ),
            # Outside the 7-day window: must not be counted.
            SourceFetchLog(
                source_id=failing.id,
                attempted_at=now - timedelta(days=30),
                outcome="failure",
                failure_code="http_403",
            ),
        ]
    )
    db.add(
        Content(
            source_id=healthy.id,
            external_id="c-1",
            title="Recent item",
            original_url="https://example.com/healthy/post",
            content_type="rss",
            fetched_at=now - timedelta(days=1),
        )
    )
    db.commit()

    report = build_weekly_health_report(db, now=now)

    assert report["fetch"]["attempts"] == 3
    assert report["fetch"]["success"] == 1
    assert report["fetch"]["failure"] == 2
    assert report["fetch"]["fulltext_ok"] == 2
    assert report["fetch"]["fulltext_total"] == 3
    assert report["fetch"]["fulltext_rate"] == pytest.approx(2 / 3, abs=1e-3)

    assert len(report["top_failing_sources"]) == 1
    top = report["top_failing_sources"][0]
    assert top["source_name"] == "failing"
    assert top["failures"] == 2
    assert top["failure_code"] == "http_429"

    assert report["session_issues"] == [
        {"source_name": "failing", "status": "expired", "reason": "cookie_expired"}
    ]
    assert report["disabled_sources"] == 1
    assert report["cooldown_sources"] == 1
    assert report["new_content_count"] == 1

    db.close()


def test_build_weekly_health_report_empty_db(session_factory):
    db = session_factory()
    report = build_weekly_health_report(db)

    assert report["fetch"]["attempts"] == 0
    assert report["fetch"]["fulltext_rate"] is None
    assert report["top_failing_sources"] == []
    assert report["session_issues"] == []
    assert report["new_content_count"] == 0
    db.close()


def test_load_eval_history_summary_reports_recent_metrics(tmp_path):
    history = tmp_path / "eval_history.jsonl"
    history.write_text(
        "\n".join(
            [
                '{"ran_at":"2026-07-01T00:00:00Z","metrics":{"precision@20":0.5,"duplicate_rate":0.1,"fulltext_complete_rate":0.8,"source_coverage@20":0.3}}',
                "not json",
                '{"ran_at":"2026-07-02T00:00:00Z","metrics":{"precision@20":0.6,"duplicate_rate":0.08,"fulltext_complete_rate":0.9,"source_coverage@20":0.35}}',
            ]
        ),
        encoding="utf-8",
    )

    summary = _load_eval_history_summary(history)

    assert summary is not None
    assert summary["points"] == 2
    assert summary["recent_points"] == 2
    assert summary["latest_ran_at"] == "2026-07-02T00:00:00Z"
    assert summary["metrics"]["precision@20"] == {
        "value": 0.6,
        "previous": 0.5,
        "delta": 0.1,
    }
    assert summary["metrics"]["duplicate_rate"]["delta"] == -0.02


def test_load_eval_history_summary_missing_file_returns_none(tmp_path):
    assert _load_eval_history_summary(tmp_path / "missing.jsonl") is None


def test_build_weekly_health_report_includes_eval_history(session_factory, tmp_path):
    db = session_factory()
    history = tmp_path / "eval_history.jsonl"
    history.write_text(
        '{"ran_at":"2026-07-02T00:00:00Z","metrics":{"precision@20":0.7}}\n',
        encoding="utf-8",
    )

    report = build_weekly_health_report(db, eval_history_path=history)

    assert report["offline_eval"]["points"] == 1
    assert report["offline_eval"]["metrics"]["precision@20"]["value"] == 0.7
    db.close()


def test_render_weekly_report_html_escapes_and_includes_metrics(session_factory):
    db = session_factory()
    source = _make_source(
        db,
        name="<b>evil</b>",
        session_health_status="expired",
        session_health_reason="cookie_expired",
    )
    db.add(
        SourceFetchLog(
            source_id=source.id,
            attempted_at=utcnow_naive() - timedelta(days=1),
            outcome="failure",
            failure_code="bot_wall",
        )
    )
    db.commit()

    html_body = _render_weekly_report_html(build_weekly_health_report(db))

    assert "PIM 每周体检" in html_body
    assert "bot_wall" in html_body
    assert "cookie_expired" in html_body
    assert "<b>evil</b>" not in html_body  # escaped
    assert "&lt;b&gt;evil&lt;/b&gt;" in html_body
    db.close()


def test_render_weekly_report_html_includes_eval_history():
    html_body = _render_weekly_report_html(
        {
            "window_days": 7,
            "generated_at": "2026-07-06T00:00:00",
            "fetch": {},
            "top_failing_sources": [],
            "session_issues": [],
            "disabled_sources": 0,
            "cooldown_sources": 0,
            "new_content_count": 0,
            "offline_eval": {
                "latest_ran_at": "2026-07-05T00:00:00Z",
                "points": 4,
                "metrics": {
                    "precision@20": {"value": 0.75, "previous": 0.7, "delta": 0.05},
                    "duplicate_rate": {"value": 0.01, "previous": 0.02, "delta": -0.01},
                    "fulltext_complete_rate": {"value": 0.9, "previous": None, "delta": None},
                    "source_coverage@20": {"value": 0.4, "previous": 0.35, "delta": 0.05},
                },
            },
        }
    )

    assert "离线评测趋势" in html_body
    assert "precision@20" in html_body
    assert "+0.0500" in html_body
    assert "-0.0100" in html_body
    assert "2026-07-05T00:00:00Z" in html_body


def test_weekly_report_job_is_registered():
    from app.scheduler import scheduler, setup_scheduler

    scheduler.remove_all_jobs()
    setup_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "send_weekly_health_report_email" in job_ids
    scheduler.remove_all_jobs()
