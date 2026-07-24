"""Dependency-free metrics for Core and Event formal evaluation."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from typing import Any


def _safe_ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def binary_classification_metrics(expected: Sequence[bool], predicted: Sequence[bool]) -> dict[str, Any]:
    """Return confusion counts and precision/recall/F1 for aligned labels."""

    if len(expected) != len(predicted):
        raise ValueError("expected and predicted must have equal length")
    tp = sum(1 for truth, guess in zip(expected, predicted, strict=True) if truth and guess)
    fp = sum(1 for truth, guess in zip(expected, predicted, strict=True) if not truth and guess)
    tn = sum(1 for truth, guess in zip(expected, predicted, strict=True) if not truth and not guess)
    fn = sum(1 for truth, guess in zip(expected, predicted, strict=True) if truth and not guess)
    precision = _safe_ratio(tp, tp + fp)
    recall = _safe_ratio(tp, tp + fn)
    f1 = _safe_ratio(2 * precision * recall, precision + recall)
    return {
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "accuracy": round(_safe_ratio(tp + tn, len(expected)), 6),
        "confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
    }


def ranking_metrics(
    relevance: Sequence[float],
    scores: Sequence[float],
    *,
    k: int = 20,
) -> dict[str, Any]:
    """Compute NDCG@K, MRR and Recall@K from graded relevance."""

    if len(relevance) != len(scores):
        raise ValueError("relevance and scores must have equal length")
    if k <= 0:
        raise ValueError("k must be positive")
    order = sorted(range(len(scores)), key=lambda index: (scores[index], -index), reverse=True)
    ranked = [max(0.0, float(relevance[index])) for index in order[:k]]
    ideal = sorted((max(0.0, float(value)) for value in relevance), reverse=True)[:k]

    def dcg(values: Iterable[float]) -> float:
        return sum((2**gain - 1) / math.log2(rank + 2) for rank, gain in enumerate(values))

    ideal_dcg = dcg(ideal)
    first_relevant = next((rank + 1 for rank, gain in enumerate(ranked) if gain > 0), None)
    relevant_total = sum(1 for value in relevance if value > 0)
    relevant_found = sum(1 for value in ranked if value > 0)
    return {
        f"ndcg@{k}": round(_safe_ratio(dcg(ranked), ideal_dcg), 6),
        "mrr": round(1 / first_relevant, 6) if first_relevant else 0.0,
        f"recall@{k}": round(_safe_ratio(relevant_found, relevant_total), 6),
    }


def calibration_metrics(expected: Sequence[bool], probabilities: Sequence[float], *, bins: int = 10) -> dict[str, Any]:
    """Return Brier score, ECE and reliability-diagram points."""

    if len(expected) != len(probabilities):
        raise ValueError("expected and probabilities must have equal length")
    if bins <= 0:
        raise ValueError("bins must be positive")
    if not expected:
        return {"brier": None, "ece": None, "reliability": []}

    clipped = [min(1.0, max(0.0, float(value))) for value in probabilities]
    brier = sum((probability - float(truth)) ** 2 for truth, probability in zip(expected, clipped, strict=True))
    brier /= len(expected)
    buckets: list[list[tuple[bool, float]]] = [[] for _ in range(bins)]
    for truth, probability in zip(expected, clipped, strict=True):
        bucket_index = min(bins - 1, int(probability * bins))
        buckets[bucket_index].append((truth, probability))

    reliability: list[dict[str, Any]] = []
    ece = 0.0
    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        confidence = sum(probability for _, probability in bucket) / len(bucket)
        observed = sum(1 for truth, _ in bucket if truth) / len(bucket)
        ece += len(bucket) / len(expected) * abs(confidence - observed)
        reliability.append(
            {
                "bin": index,
                "lower": round(index / bins, 6),
                "upper": round((index + 1) / bins, 6),
                "count": len(bucket),
                "mean_probability": round(confidence, 6),
                "observed_rate": round(observed, 6),
            }
        )
    return {"brier": round(brier, 6), "ece": round(ece, 6), "reliability": reliability}


def confidence_interval(
    values: Sequence[Any],
    statistic: Callable[[Sequence[Any]], float],
    *,
    rounds: int = 500,
    confidence: float = 0.95,
    seed: int = 20260722,
) -> dict[str, float | int | None]:
    """Return a deterministic percentile bootstrap confidence interval."""

    if not values:
        return {"value": None, "low": None, "high": None, "confidence": confidence, "rounds": rounds}
    if rounds <= 0 or not 0 < confidence < 1:
        raise ValueError("rounds must be positive and confidence must be between zero and one")
    randomizer = random.Random(seed)
    samples = []
    for _ in range(rounds):
        resample = [values[randomizer.randrange(len(values))] for _ in values]
        samples.append(float(statistic(resample)))
    samples.sort()
    tail = (1 - confidence) / 2
    low_index = max(0, min(len(samples) - 1, int(math.floor(tail * len(samples)))))
    high_index = max(0, min(len(samples) - 1, int(math.ceil((1 - tail) * len(samples))) - 1))
    return {
        "value": round(float(statistic(values)), 6),
        "low": round(samples[low_index], 6),
        "high": round(samples[high_index], 6),
        "confidence": confidence,
        "rounds": rounds,
    }


def cluster_metrics(expected: dict[str, str], predicted: dict[str, str]) -> dict[str, float]:
    """Compute B-cubed precision/recall/F1 and assignment ID churn."""

    item_ids = sorted(set(expected) & set(predicted))
    if not item_ids:
        return {"b_cubed_precision": 0.0, "b_cubed_recall": 0.0, "b_cubed_f1": 0.0, "id_churn": 0.0}
    expected_members: dict[str, set[str]] = defaultdict(set)
    predicted_members: dict[str, set[str]] = defaultdict(set)
    for item_id in item_ids:
        expected_members[expected[item_id]].add(item_id)
        predicted_members[predicted[item_id]].add(item_id)
    precisions = []
    recalls = []
    for item_id in item_ids:
        overlap = expected_members[expected[item_id]] & predicted_members[predicted[item_id]]
        precisions.append(_safe_ratio(len(overlap), len(predicted_members[predicted[item_id]])))
        recalls.append(_safe_ratio(len(overlap), len(expected_members[expected[item_id]])))
    precision = sum(precisions) / len(precisions)
    recall = sum(recalls) / len(recalls)
    f1 = _safe_ratio(2 * precision * recall, precision + recall)

    # Cluster identifiers are stable product identities. This metric is exact,
    # while B-cubed remains invariant to harmless cluster-label renaming.
    churn = sum(1 for item_id in item_ids if expected[item_id] != predicted[item_id]) / len(item_ids)
    return {
        "b_cubed_precision": round(precision, 6),
        "b_cubed_recall": round(recall, 6),
        "b_cubed_f1": round(f1, 6),
        "id_churn": round(churn, 6),
    }
