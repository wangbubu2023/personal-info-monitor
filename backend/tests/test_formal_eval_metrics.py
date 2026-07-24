from __future__ import annotations

import pytest

from app.domains.eval.metrics import (
    binary_classification_metrics,
    calibration_metrics,
    cluster_metrics,
    confidence_interval,
    ranking_metrics,
)


def test_binary_classification_metrics_reports_confusion_and_f1():
    metrics = binary_classification_metrics([True, True, False, False], [True, False, True, False])

    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert metrics["f1"] == 0.5
    assert metrics["confusion_matrix"] == {"tp": 1, "fp": 1, "tn": 1, "fn": 1}


def test_binary_metrics_reject_unaligned_inputs():
    with pytest.raises(ValueError):
        binary_classification_metrics([True], [])


def test_ranking_metrics_reports_ndcg_mrr_and_recall():
    metrics = ranking_metrics([2, 0, 1], [0.9, 0.8, 0.7], k=2)

    assert 0 < metrics["ndcg@2"] < 1
    assert metrics["mrr"] == 1.0
    assert metrics["recall@2"] == 0.5


def test_calibration_metrics_builds_reliability_points():
    metrics = calibration_metrics([True, False, True, False], [0.9, 0.8, 0.6, 0.1], bins=2)

    assert metrics["brier"] == 0.205
    assert metrics["ece"] == 0.1
    assert sum(point["count"] for point in metrics["reliability"]) == 4


def test_confidence_interval_is_deterministic():
    values = [1.0, 2.0, 3.0, 4.0]
    first = confidence_interval(values, lambda sample: sum(sample) / len(sample), rounds=50)
    second = confidence_interval(values, lambda sample: sum(sample) / len(sample), rounds=50)

    assert first == second
    assert first["value"] == 2.5
    assert first["low"] <= first["value"] <= first["high"]


def test_cluster_metrics_reports_b_cubed_and_id_churn():
    metrics = cluster_metrics(
        {"a": "event-1", "b": "event-1", "c": "event-2"},
        {"a": "event-1", "b": "event-2", "c": "event-2"},
    )

    assert metrics["b_cubed_precision"] == pytest.approx(2 / 3, abs=1e-6)
    assert metrics["b_cubed_recall"] == pytest.approx(2 / 3, abs=1e-6)
    assert metrics["id_churn"] == pytest.approx(1 / 3, abs=1e-6)
