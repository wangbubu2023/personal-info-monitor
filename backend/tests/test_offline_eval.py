from __future__ import annotations

import json

from scripts.run_offline_eval import compute_metrics, run_offline_eval


def _record(idx: int, **overrides):
    base = {
        "id": f"r{idx}",
        "title": f"Story {idx}",
        "url": f"https://source{idx}.example/story",
        "publish_time": f"2026-07-01T0{idx}:00:00",
        "fetched_at": f"2026-07-01T0{idx}:10:00",
        "label": "ok",
        "article_score": 100 - idx,
        "summary": "summary",
        "full_content": "body " * 80,
        "metadata": {"fulltext_status": "full"},
    }
    base.update(overrides)
    return base


def test_compute_metrics_reports_core_eval_numbers():
    records = [
        _record(1, label="must_see", article_score=100, source_url="https://a.example"),
        _record(
            2,
            label="noise",
            article_score=90,
            source_url="https://b.example",
            is_duplicate_of="r1",
            fetched_at="2026-07-01T02:30:00",
        ),
        _record(
            3,
            label="ok",
            article_score=80,
            source_url="https://a.example",
            metadata={"fulltext_status": "title_only"},
            full_content="",
            summary="",
            fetched_at="2026-07-01T03:50:00",
        ),
        _record(
            4,
            label="noise",
            article_score=70,
            source_url="https://c.example",
            fetched_at="2026-07-01T04:10:00",
        ),
    ]

    metrics = compute_metrics(records)

    assert metrics["total"] == 4
    assert metrics["precision@20"] == 0.5
    assert metrics["duplicate_rate"] == 0.25
    assert metrics["freshness_lag_p50"] == 10.0
    assert metrics["freshness_lag_p90"] == 50.0
    assert metrics["fulltext_complete_rate"] == 0.75
    assert metrics["title_only_rate"] == 0.25
    assert metrics["source_diversity@20"] == 3
    assert metrics["source_coverage@20"] == 1.0
    assert metrics["covered_sources@20"] == 3
    assert metrics["total_sources"] == 3


def test_compute_metrics_reports_source_coverage_at_k():
    records = [
        _record(1, article_score=100, source_id=1, source_url="https://a.example"),
        _record(2, article_score=90, source_id=1, source_url="https://a.example/other"),
        _record(3, article_score=80, source_id=2, source_url="https://b.example"),
        _record(4, article_score=70, source_id=3, source_url="https://c.example"),
    ]

    metrics = compute_metrics(records, top_k=2)

    assert metrics["source_diversity@20"] == 1
    assert metrics["source_coverage@20"] == 0.3333
    assert metrics["covered_sources@20"] == 1
    assert metrics["total_sources"] == 3


def test_run_offline_eval_appends_history(tmp_path):
    eval_set = tmp_path / "eval_set.jsonl"
    history = tmp_path / "history.jsonl"
    rows = [_record(1), _record(2, label="noise", is_duplicate_of="r1")]
    eval_set.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    result = run_offline_eval(eval_set, history_path=history, append_history=True)

    assert result["metrics"]["total"] == 2
    history_rows = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()]
    assert len(history_rows) == 1
    assert history_rows[0]["metrics"]["duplicate_rate"] == 0.5
