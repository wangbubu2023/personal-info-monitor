"""Backwards-compatible facade for the baseline scoring helpers.

Implementation has moved to :mod:`app.domains.ingest.scoring` as part of
Phase 3 step 4 of the module-refactor blueprint. This shim re-exports
every public symbol — the ``SCORE_VERSION`` constant,
``FULLTEXT_CONFIDENCE`` / ``FULLTEXT_STATUS_LABELS`` tables,
:class:`ScoringConfig`, and the full helper set
(``calculate_final_score``, ``merge_scoring_metadata``,
``merge_baseline_scoring_metadata``, ``compute_domain_match``,
``estimate_baseline_dimension_scores``, ``compute_score_confidence``,
``build_recommendation_reason``, plus the ``clamp_float`` /
``normalize_*`` utilities) — so existing imports
(``tasks/process_tasks.py``, ``tests/test_content_quality_scoring.py``)
keep working.

.. deprecated::
   Import directly from :mod:`app.domains.ingest.scoring`. This shim
   will be removed in Phase 7.
"""

from app.domains.ingest.scoring import (  # noqa: F401 — re-export
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
]
