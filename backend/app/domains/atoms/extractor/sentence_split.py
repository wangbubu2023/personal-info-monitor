"""Split article text into candidate sentences for atom extraction."""

from __future__ import annotations

import re

_MIN_SENTENCE_LEN = 8

# Chinese and Western sentence terminators
_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s*|\n+")


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


def batch_sentences(sentences: list[str], batch_size: int = 12) -> list[list[str]]:
    if batch_size <= 0:
        return [sentences]
    return [sentences[i : i + batch_size] for i in range(0, len(sentences), batch_size)]


__all__ = ["batch_sentences", "split_sentences"]
