"""Subjective score slot for pim-score-v2 (LLM hook + fixed baseline)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.features import feature_enabled

FIXED_BASELINE_SUBJECTIVE_SCORE = 5.0


@dataclass(frozen=True)
class SubjectiveScoreResult:
    score: float
    source: str
    rationale: str | None = None
    model: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "score": round(max(0.0, min(10.0, float(self.score))), 1),
            "source": self.source,
            "rationale": self.rationale,
            "model": self.model,
        }


class SubjectiveScorer(Protocol):
    async def score(self, content: Any, *, lane: str) -> SubjectiveScoreResult: ...


class FixedBaselineSubjectiveScorer:
    """Neutral placeholder until LLM subjective scoring is enabled."""

    def __init__(self, score: float = FIXED_BASELINE_SUBJECTIVE_SCORE) -> None:
        self._score = score

    async def score(self, content: Any, *, lane: str) -> SubjectiveScoreResult:
        return SubjectiveScoreResult(
            score=self._score,
            source="fixed_baseline",
            rationale=None,
            model=None,
        )


def get_subjective_scorer() -> SubjectiveScorer:
    if feature_enabled("PIM_SCORE_LLM_SUBJECTIVE"):
        # Future: return LlmSubjectiveScorer()
        pass
    return FixedBaselineSubjectiveScorer()


def resolve_subjective_score(content: Any, *, lane: str) -> SubjectiveScoreResult:
    """Sync path for ingest finish (fixed baseline until LLM sidecar exists)."""
    del content, lane
    if feature_enabled("PIM_SCORE_LLM_SUBJECTIVE"):
        pass
    return SubjectiveScoreResult(
        score=FIXED_BASELINE_SUBJECTIVE_SCORE,
        source="fixed_baseline",
        rationale=None,
        model=None,
    )


async def score_subjective_sync_path(content: Any, *, lane: str) -> SubjectiveScoreResult:
    """Async alias; currently identical to :func:`resolve_subjective_score`."""
    return resolve_subjective_score(content, lane=lane)
