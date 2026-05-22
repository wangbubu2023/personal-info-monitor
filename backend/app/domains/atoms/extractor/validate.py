"""Validate extracted atoms against source text."""

from __future__ import annotations

import re

from app.domains.atoms.extractor.sentence_split import split_sentences

# Normalize common LLM / HTML punctuation differences before matching.
_PUNCT_MAP = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u00a0": " ",
        "\u200b": "",
        "\u2060": "",
    }
)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _normalize_for_match(text: str) -> str:
    return _normalize_whitespace((text or "").translate(_PUNCT_MAP))


def sentence_in_source(source_sentence: str, full_text: str) -> bool:
    """Return True when *source_sentence* appears in *full_text* (punctuation-tolerant)."""
    return resolve_source_sentence(source_sentence, full_text) is not None


def resolve_source_sentence(source_sentence: str, full_text: str) -> str | None:
    """Return the canonical sentence from *full_text* when a tolerant match exists."""
    sentence = (source_sentence or "").strip()
    body = full_text or ""
    if not sentence or not body:
        return None
    if sentence in body:
        return sentence

    norm_target = _normalize_for_match(sentence)
    if not norm_target:
        return None

    norm_body = _normalize_for_match(body)
    if norm_target in norm_body:
        for candidate in split_sentences(body):
            if _normalize_for_match(candidate) == norm_target:
                return candidate
        return sentence

    for candidate in split_sentences(body):
        norm_candidate = _normalize_for_match(candidate)
        if norm_candidate == norm_target:
            return candidate
        if len(norm_target) >= 24 and (
            norm_target in norm_candidate or norm_candidate in norm_target
        ):
            return candidate

    return None


__all__ = ["resolve_source_sentence", "sentence_in_source"]
