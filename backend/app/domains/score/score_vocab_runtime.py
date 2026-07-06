"""Runtime scoring vocabulary — static score_vocab + user keywords.

User-configured :class:`~app.models.keyword.Keyword` rows are tracked alongside
the static rule vocabulary and contribute only a capped salience bonus when
they actually matched the current article.
"""

from __future__ import annotations

import re as _re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.domains.ingest.keywords.rules import normalize_keyword_value
USER_KEYWORD_SALIENCE_BONUS_PER_TERM = 1.0
USER_KEYWORD_SALIENCE_BONUS_MAX = 2.0


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
        from app.domains.score import score_vocab

        return cls(
            entity_tier_s=score_vocab.ENTITY_TIER_S,
            entity_tier_a=score_vocab.ENTITY_TIER_A,
            entity_tier_b=score_vocab.ENTITY_TIER_B,
            user_keyword_terms=user_all,
            matched_user_terms=user_matched,
        )

    def entity_tier_score(self, corpus: str) -> float:
        from app.domains.score import score_vocab

        corpus_l = (corpus or "").lower()
        for term in self.entity_tier_s:
            if _term_in_corpus(term, corpus_l):
                return score_vocab.ENTITY_TIER_SCORES["S"]
        for term in self.entity_tier_a:
            if _term_in_corpus(term, corpus_l):
                return score_vocab.ENTITY_TIER_SCORES["A"]
        for term in self.entity_tier_b:
            if _term_in_corpus(term, corpus_l):
                return score_vocab.ENTITY_TIER_SCORES["B"]
        return score_vocab.ENTITY_TIER_SCORES["C"]

    def user_keyword_salience_bonus(self, corpus: str) -> float:
        """Capped additive salience bonus for user keywords matched on this article."""
        if not self.matched_user_terms:
            return 0.0
        corpus_l = (corpus or "").lower()
        matched_count = sum(1 for term in self.matched_user_terms if _term_in_corpus(term, corpus_l))
        return min(USER_KEYWORD_SALIENCE_BONUS_MAX, matched_count * USER_KEYWORD_SALIENCE_BONUS_PER_TERM)


def _is_ascii_term(term: str) -> bool:
    """True when term consists only of ASCII characters (English words, numbers, punctuation)."""
    return all(ord(c) < 128 for c in term)


def _term_in_corpus(term: str, corpus_l: str) -> bool:
    """Match term in corpus. ASCII terms use word-boundary regex; CJK terms use substring match."""
    t = term.lower()
    if not t:
        return False
    if _is_ascii_term(term):
        return bool(_re.search(r"\b" + _re.escape(t) + r"\b", corpus_l))
    return t in corpus_l


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
