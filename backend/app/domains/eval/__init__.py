"""Offline evaluation primitives used by release gates and reports."""

from app.domains.eval.metrics import (
    binary_classification_metrics,
    calibration_metrics,
    cluster_metrics,
    confidence_interval,
    ranking_metrics,
)

__all__ = [
    "binary_classification_metrics",
    "calibration_metrics",
    "cluster_metrics",
    "confidence_interval",
    "ranking_metrics",
]
