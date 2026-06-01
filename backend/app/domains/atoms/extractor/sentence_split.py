"""Split article text into candidate sentences for atom extraction."""

from __future__ import annotations

import re

from app.domains.ingest.summary_clean import text_hits_atom_boilerplate

_MIN_SENTENCE_LEN = 8

# Quality thresholds for candidate sentences (post-split filtering).
_MIN_CJK_LEN = 20
_MIN_EN_WORDS = 6
_MAX_CODE_SYMBOL_RATIO = 0.20

# Chinese and Western sentence terminators
_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s*|\n+")

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_CODE_SYMBOL_RE = re.compile(r"[{}\[\]();=<>|/\\`$#*]")
_DIGIT_RE = re.compile(r"\d")
_VERB_HINT_RE = re.compile(
    r"\b(is|are|was|were|be|has|have|had|will|would|can|could|should|may|might|"
    r"announced|released|said|reported|launched|raised|reached|grew|fell|rose)\b",
    re.IGNORECASE,
)


def split_sentences(text: str) -> list[str]:
    """Return deduplicated sentences in source order."""
    raw = (text or "").strip()
    if not raw:
        return []

    parts: list[str] = []
    for chunk in _SPLIT_RE.split(raw):
        sentence = chunk.strip()
        if len(sentence) < _MIN_SENTENCE_LEN:
            continue
        parts.append(sentence)

    seen: set[str] = set()
    ordered: list[str] = []
    for sentence in parts:
        if sentence in seen:
            continue
        seen.add(sentence)
        ordered.append(sentence)
    return ordered


def _code_symbol_ratio(sentence: str) -> float:
    if not sentence:
        return 0.0
    return len(_CODE_SYMBOL_RE.findall(sentence)) / len(sentence)


def sentence_quality_reason(sentence: str) -> str | None:
    """Return a rejection reason for a low-quality candidate sentence, else ``None``.

    Used to keep boilerplate, code fragments, list labels, and isolated short
    fragments out of the LLM input. Returns ``None`` for sentences worth analyzing.
    """
    text = (sentence or "").strip()
    if not text:
        return "empty"

    if text_hits_atom_boilerplate(text):
        return "boilerplate"

    if _code_symbol_ratio(text) > _MAX_CODE_SYMBOL_RATIO:
        return "code_like"

    has_cjk = bool(_CJK_RE.search(text))
    if has_cjk:
        if len(text) < _MIN_CJK_LEN:
            return "short_cjk"
    else:
        words = text.split()
        if len(words) < _MIN_EN_WORDS:
            return "short_en"

    # Label / column-header style: ends with a colon and lacks a real predicate.
    if text.endswith((":", "：")):
        if has_cjk or not _VERB_HINT_RE.search(text):
            return "label_like"

    # Title Case phrase with no verb and no number (e.g. "Basic Commands").
    if not has_cjk:
        words = text.split()
        if (
            len(words) <= 6
            and not _DIGIT_RE.search(text)
            and not _VERB_HINT_RE.search(text)
            and sum(1 for w in words if w[:1].isupper()) >= max(1, len(words) - 1)
        ):
            return "title_like"

    return None


def filter_candidate_sentences(sentences: list[str]) -> tuple[list[str], dict[str, int]]:
    """Split sentences into kept candidates and a per-reason rejection histogram."""
    kept: list[str] = []
    stats: dict[str, int] = {}
    for sentence in sentences:
        reason = sentence_quality_reason(sentence)
        if reason is None:
            kept.append(sentence)
            continue
        stats[reason] = stats.get(reason, 0) + 1
    return kept, stats


def batch_sentences(sentences: list[str], batch_size: int = 12) -> list[list[str]]:
    if batch_size <= 0:
        return [sentences]
    return [sentences[i : i + batch_size] for i in range(0, len(sentences), batch_size)]


__all__ = [
    "batch_sentences",
    "filter_candidate_sentences",
    "sentence_quality_reason",
    "split_sentences",
]
