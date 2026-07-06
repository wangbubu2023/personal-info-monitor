from __future__ import annotations

import json

from scripts.check_eval_history import check_eval_history


def _write_history(path, values):
    rows = [
        {
            "ran_at": f"2026-07-0{index}T00:00:00+00:00",
            "eval_set": "tests/fixtures/eval_set.jsonl",
            "metrics": {"precision@20": value},
        }
        for index, value in enumerate(values, start=1)
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_check_eval_history_accepts_enough_non_regressing_points(tmp_path):
    history = tmp_path / "eval_history.jsonl"
    _write_history(history, [0.5, 0.55, 0.6, 0.6])

    result = check_eval_history(history)

    assert result.ok is True
    assert result.history_points == 4
    assert result.latest_value == 0.6
    assert result.baseline_value == 0.6
    assert result.errors == []


def test_check_eval_history_reports_too_few_points(tmp_path):
    history = tmp_path / "eval_history.jsonl"
    _write_history(history, [0.5, 0.55, 0.6])

    result = check_eval_history(history)

    assert result.ok is False
    assert result.history_points == 3
    assert result.errors == ["history has 3 point(s), expected at least 4"]


def test_check_eval_history_reports_metric_regression(tmp_path):
    history = tmp_path / "eval_history.jsonl"
    _write_history(history, [0.5, 0.6, 0.7, 0.65])

    result = check_eval_history(history)

    assert result.ok is False
    assert result.errors == ["precision@20 regressed: latest=0.6500, previous=0.7000, max_drop=0.0000"]


def test_check_eval_history_reports_missing_latest_metric(tmp_path):
    history = tmp_path / "eval_history.jsonl"
    rows = [
        {"metrics": {"precision@20": 0.5}},
        {"metrics": {"precision@20": 0.55}},
        {"metrics": {"precision@20": 0.6}},
        {"metrics": {"duplicate_rate": 0.0}},
    ]
    history.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    result = check_eval_history(history)

    assert result.ok is False
    assert result.errors == ["latest history point is missing numeric metric precision@20"]
