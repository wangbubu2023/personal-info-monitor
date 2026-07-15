"""Subjective score slot for pim-score-v2 (LLM hook + fixed baseline)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

FIXED_BASELINE_SUBJECTIVE_SCORE = 5.0

_SCORE_RE = re.compile(r"\b([1-9]|10)\b")


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


class LlmSubjectiveScorer:
    """Score relevance via LLM when the product-level subjective scoring switch is enabled."""

    _SYSTEM = (
        "你是新闻重要性评估助手。根据标题和摘要，给出对个人信息监控用途的主观重要性分数（1-10整数）和一句不超过30字的理由。"
        "输出格式（只输出这两行）：\n"
        "score: <1-10整数>\n"
        "rationale: <理由>"
    )

    async def score(self, content: Any, *, lane: str) -> SubjectiveScoreResult:
        title = (getattr(content, "title", None) or getattr(content, "translated_title", None) or "").strip()
        summary = (getattr(content, "summary", None) or getattr(content, "translated_summary", None) or "").strip()
        if not title and not summary:
            return SubjectiveScoreResult(score=FIXED_BASELINE_SUBJECTIVE_SCORE, source="fixed_baseline")

        prompt = f"标题：{title[:200]}\n摘要：{summary[:400]}"
        raw = await self._call_llm(prompt)
        return self._parse(raw)

    async def _call_llm(self, prompt: str) -> str:
        try:
            from app.ai.provider import ModelProviderClient, get_runtime_from_system_settings
            runtime = await get_runtime_from_system_settings(
                setting_key="score_model",
                default_provider="ollama",
                default_model="",
                default_max_tokens=150,
            )
            if runtime is None:
                return ""
            client = ModelProviderClient()
            return await client.generate_text(
                runtime,
                prompt=prompt,
                system_prompt=self._SYSTEM,
                temperature=0.1,
                max_tokens=150,
                timeout_seconds=30.0,
            )
        except Exception:  # noqa: BLE001 - subjective LLM scoring falls back to deterministic parse
            return ""

    def _parse(self, raw: str) -> SubjectiveScoreResult:
        if not (raw or "").strip():
            return SubjectiveScoreResult(score=FIXED_BASELINE_SUBJECTIVE_SCORE, source="fixed_baseline")
        score = FIXED_BASELINE_SUBJECTIVE_SCORE
        rationale: str | None = None
        for line in (raw or "").splitlines():
            line = line.strip()
            if line.lower().startswith("score:"):
                m = _SCORE_RE.search(line)
                if m:
                    score = float(m.group(1))
            elif line.lower().startswith("rationale:"):
                rationale = line.split(":", 1)[-1].strip() or None
        return SubjectiveScoreResult(
            score=score,
            source="llm",
            rationale=rationale,
            model=None,
        )


async def subjective_scoring_effective() -> bool:
    from app.platform.llm.policy import resolve_subjective_scoring_state

    return (await resolve_subjective_scoring_state()).effective


async def get_subjective_scorer() -> SubjectiveScorer:
    if await subjective_scoring_effective():
        return LlmSubjectiveScorer()
    return FixedBaselineSubjectiveScorer()


def resolve_subjective_score(content: Any, *, lane: str) -> SubjectiveScoreResult:
    """Sync path for ingest finish — always returns fixed baseline (LLM is async-only)."""
    del content, lane
    return SubjectiveScoreResult(
        score=FIXED_BASELINE_SUBJECTIVE_SCORE,
        source="fixed_baseline",
        rationale=None,
        model=None,
    )


async def score_subjective_async(content: Any, *, lane: str) -> SubjectiveScoreResult:
    """Async path — calls LLM when product policy is effective, else fixed baseline."""
    scorer = await get_subjective_scorer()
    return await scorer.score(content, lane=lane)
