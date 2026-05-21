"""Backwards-compatible facade for the baseline scoring helpers.

Implementation lives in :mod:`app.domains.score.scoring`.
"""

from app.domains.score.scoring import (  # noqa: F401 — re-export
    FULLTEXT_CONFIDENCE,
    FULLTEXT_STATUS_LABELS,
    SCORE_VERSION,
    ScoringConfig,
    build_recommendation_reason,
    calculate_final_score,
    clamp_float,
    compute_domain_match,
    compute_score_confidence,
    estimate_baseline_dimension_scores,
    merge_baseline_scoring_metadata,
    merge_rule_scoring_metadata,
    merge_scoring_metadata,
    normalize_dimension_score,
    normalize_source_stars,
)

__all__ = [
    "SCORE_VERSION",
    "FULLTEXT_CONFIDENCE",
    "FULLTEXT_STATUS_LABELS",
    "ScoringConfig",
    "clamp_float",
    "normalize_source_stars",
    "normalize_dimension_score",
    "compute_domain_match",
    "estimate_baseline_dimension_scores",
    "compute_score_confidence",
    "build_recommendation_reason",
    "calculate_final_score",
    "merge_scoring_metadata",
    "merge_baseline_scoring_metadata",
    "merge_rule_scoring_metadata",
]
