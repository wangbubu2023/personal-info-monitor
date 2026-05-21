"""Runtime scoring vocabulary — static score_vocab + user keywords.

User-configured :class:`~app.models.keyword.Keyword` rows are merged into the
rule-based entity tiers so keywords are always a subset of the effective
scoring vocabulary, not a parallel list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.domains.ingest.keywords.rules import normalize_keyword_value
from app.domains.score.score_vocab import (
    ENTITY_TIER_A,
    ENTITY_TIER_B,
    ENTITY_TIER_S,
    ENTITY_TIER_SCORES,
    _merge,
)

# User keyword hit on this article — salience floor (between A and B).
USER_KEYWORD_MATCHED_SALIENCE = ENTITY_TIER_SCORES["A"]


@dataclass(frozen=True)
class RuntimeScoringVocab:
    """Effective entity tiers after merging static vocab with user keywords."""

    entity_tier_s: tuple[str, ...]
    entity_tier_a: tuple[str, ...]
    entity_tier_b: tuple[str, ...]
    user_keyword_terms: tuple[str, ...]
    matched_user_terms: tuple[str, ...]

    @classmethod
    def build(
        cls,
        user_keyword_terms: Sequence[str] | None = None,
        matched_user_terms: Sequence[str] | None = None,
    ) -> RuntimeScoringVocab:
        user_all = _dedupe_terms(user_keyword_terms or ())
        user_matched = _dedupe_terms(matched_user_terms or ())
        # User keywords are part of tier B in the combined vocabulary.
        tier_b = _merge(ENTITY_TIER_B, user_all)
        return cls(
            entity_tier_s=ENTITY_TIER_S,
            entity_tier_a=ENTITY_TIER_A,
            entity_tier_b=tier_b,
            user_keyword_terms=user_all,
            matched_user_terms=user_matched,
        )

    def entity_tier_score(self, corpus: str) -> float:
        corpus_l = (corpus or "").lower()
        for term in self.entity_tier_s:
            if term.lower() in corpus_l:
                return ENTITY_TIER_SCORES["S"]
        for term in self.entity_tier_a:
            if term.lower() in corpus_l:
                return ENTITY_TIER_SCORES["A"]
        for term in self.entity_tier_b:
            if term.lower() in corpus_l:
                return ENTITY_TIER_SCORES["B"]
        return ENTITY_TIER_SCORES["C"]

    def salience_with_user_match_floor(self, base_salience: float, corpus: str) -> float:
        """Raise salience when the user explicitly monitors a term that appears."""
        if not self.matched_user_terms:
            return base_salience
        corpus_l = (corpus or "").lower()
        if any(term.lower() in corpus_l for term in self.matched_user_terms):
            return max(base_salience, USER_KEYWORD_MATCHED_SALIENCE)
        return base_salience


def _dedupe_terms(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        value = normalize_keyword_value(str(raw or ""))
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return tuple(out)


def extract_keyword_vocab_terms(keywords: Sequence[Any]) -> tuple[str, ...]:
    """Collect main + equivalent terms from enabled Keyword rows."""
    collected: list[str] = []
    for keyword in keywords:
        if keyword is not None and hasattr(keyword, "enabled") and not keyword.enabled:
            continue
        main = normalize_keyword_value(str(getattr(keyword, "keyword", "") or ""))
        if main:
            collected.append(main)
        for item in getattr(keyword, "equivalent_terms", None) or []:
            value = normalize_keyword_value(str(item or ""))
            if value:
                collected.append(value)
    return _dedupe_terms(collected)


def extract_matched_keyword_terms(keyword_matches: Sequence[Mapping[str, Any]] | None) -> tuple[str, ...]:
    """Terms that actually matched on this content (from KeywordMatcher)."""
    if not keyword_matches:
        return ()
    collected: list[str] = []
    for match in keyword_matches:
        if not isinstance(match, Mapping):
            continue
        for key in ("matched_term", "keyword"):
            value = normalize_keyword_value(str(match.get(key) or ""))
            if value:
                collected.append(value)
                break
    return _dedupe_terms(collected)
