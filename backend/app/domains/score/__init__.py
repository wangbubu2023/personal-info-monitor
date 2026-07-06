"""Content scoring — pim-score-v2 article and event layers.

Runs after ingest cleaning and optional enrich summarization. Consumes
original-language ``title`` / ``summary``; listing translations are UI-only.
"""

from app.domains.score.scoring import (
    SCORE_VERSION,
    merge_baseline_scoring_metadata,
    merge_rule_scoring_metadata,
)
from app.domains.score.ranking import RankingService

__all__ = [
    "RankingService",
    "SCORE_VERSION",
    "merge_baseline_scoring_metadata",
    "merge_rule_scoring_metadata",
]
