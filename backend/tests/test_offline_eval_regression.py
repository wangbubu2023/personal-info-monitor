from __future__ import annotations

import json

import pytest

from scripts.check_offline_eval_regression import _load_thresholds, check_metric_thresholds


def test_check_metric_thresholds_accepts_metrics_inside_budget():
    violations = check_metric_thresholds(
        {"precision@20": 0.7, "duplicate_rate": 0.1},
        {"min": {"precision@20": 0.5}, "max": {"duplicate_rate": 0.25}},
    )

    assert violations == []


def test_check_metric_thresholds_reports_min_and_max_violations():
    violations = check_metric_thresholds(
        {"precision@20": 0.4, "duplicate_rate": 0.3},
        {"min": {"precision@20": 0.5}, "max": {"duplicate_rate": 0.25}},
    )

    assert [(item.metric, item.direction) for item in violations] == [
        ("precision@20", "min"),
        ("duplicate_rate", "max"),
    ]


def test_check_metric_thresholds_reports_missing_metric():
    violations = check_metric_thresholds({}, {"min": {"precision@20": 0.5}, "max": {}})

    assert len(violations) == 1
    assert violations[0].metric == "precision@20"
    assert violations[0].direction == "min"


def test_load_thresholds_requires_numeric_values(tmp_path):
    path = tmp_path / "thresholds.json"
    path.write_text(json.dumps({"min": {"precision@20": "high"}}), encoding="utf-8")

    with pytest.raises(ValueError):
        _load_thresholds(path)
