"""Validate extracted atoms against source text."""

from __future__ import annotations

import re


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def sentence_in_source(source_sentence: str, full_text: str) -> bool:
    """Return True when *source_sentence* appears verbatim (whitespace-tolerant)."""
    sentence = (source_sentence or "").strip()
    body = full_text or ""
    if not sentence or not body:
        return False
    if sentence in body:
        return True
    return _normalize_whitespace(sentence) in _normalize_whitespace(body)


__all__ = ["sentence_in_source"]
