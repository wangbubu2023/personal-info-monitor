"""End-to-end async extraction pipeline."""

from __future__ import annotations

from typing import Any

from app.ai.provider import ModelProviderClient, get_atom_extraction_runtime
from app.domains.atoms.extractor.llm_extract import build_extraction_prompt, parse_llm_atoms
from app.domains.atoms.extractor.quality import filter_atoms, rank_atoms_for_cap
from app.domains.atoms.extractor.sentence_split import (
    batch_sentences,
    filter_candidate_sentences,
    split_sentences,
)
from app.domains.atoms.types import AtomCreate
from app.domains.ingest.summary_clean import clean_for_atomization
from app.models import Content
from app.utils.logger import get_logger

logger = get_logger(__name__)

_EXTRACTOR_VERSION = 2
_MIN_BODY_LEN = 50
_FULL_CONTENT_MIN_LEN = 200

# Per-content limits prevent a single article from flooding the library.
MAX_ATOMS_PER_CONTENT = 15
MAX_ATOMS_PER_BATCH = 5


def _article_body_for_atomization(content: Content) -> str:
    """Cleaned article body used as candidate-sentence source.

    Title is intentionally excluded — it is passed to the prompt as context only.
    Prefer ``full_content``; fall back to ``summary`` when the body is too short.
    """
    body = clean_for_atomization(content.full_content)
    if len(body) >= _FULL_CONTENT_MIN_LEN:
        return body
    summary = clean_for_atomization(content.summary)
    return body if len(body) >= len(summary) else summary


async def extract_atoms_from_content(content: Content) -> tuple[list[AtomCreate], dict[str, Any]]:
    """Run LLM extraction for one Content row.

    Returns ``(atoms, metadata)``; empty list when no runtime or no extractable text.
    """
    body = _article_body_for_atomization(content)
    metadata: dict[str, Any] = {
        "extractor": "llm-v2",
        "extractor_version": _EXTRACTOR_VERSION,
        "raw_sentence_count": 0,
        "candidate_sentence_count": 0,
        "sentence_filter_stats": {},
        "atom_filter_stats": {},
        "atom_count": 0,
        "capped": False,
        "llm_model": None,
        "skipped_reason": None,
    }

    if len(body) < _MIN_BODY_LEN:
        metadata["skipped_reason"] = "body_too_short"
        return [], metadata

    raw_sentences = split_sentences(body)
    metadata["raw_sentence_count"] = len(raw_sentences)
    if not raw_sentences:
        metadata["skipped_reason"] = "no_sentences"
        return [], metadata

    sentences, sentence_filter_stats = filter_candidate_sentences(raw_sentences)
    metadata["candidate_sentence_count"] = len(sentences)
    metadata["sentence_filter_stats"] = sentence_filter_stats
    if not sentences:
        metadata["skipped_reason"] = "no_candidate_sentences"
        return [], metadata

    runtime = await get_atom_extraction_runtime()
    if runtime is None:
        metadata["skipped_reason"] = "no_ai_runtime"
        return [], metadata

    metadata["llm_model"] = f"{runtime.provider}:{runtime.model}"
    carrier = ""
    try:
        if content.source:
            carrier = content.source.name or ""
    except Exception:  # noqa: BLE001
        carrier = ""

    title = content.title or ""
    client = ModelProviderClient()
    collected: list[AtomCreate] = []
    seen_keys: set[tuple[str, str]] = set()

    for batch in batch_sentences(sentences):
        if len(collected) >= MAX_ATOMS_PER_CONTENT:
            break

        system, user = build_extraction_prompt(
            sentences=batch,
            article_title=title,
            carrier_source=carrier or "未知",
        )
        try:
            raw = await client.generate_text(
                runtime,
                prompt=user,
                system_prompt=system,
                temperature=runtime.temperature,
                max_tokens=runtime.max_tokens,
                timeout_seconds=120.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("atom LLM batch failed for content %s: %s", content.id, exc)
            continue

        if not raw:
            continue

        parsed = parse_llm_atoms(
            raw,
            content_id=str(content.id),
            source_url=content.original_url or "",
            full_text=body,
        )
        if len(parsed) > MAX_ATOMS_PER_BATCH:
            parsed = rank_atoms_for_cap(parsed)[:MAX_ATOMS_PER_BATCH]

        for atom in parsed:
            key = (atom.source_sentence, atom.atom_type.value)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            collected.append(atom)

    kept, atom_filter_stats = filter_atoms(collected, title=title, source_text=body)
    metadata["atom_filter_stats"] = atom_filter_stats

    if len(kept) > MAX_ATOMS_PER_CONTENT:
        kept = rank_atoms_for_cap(kept)[:MAX_ATOMS_PER_CONTENT]
        metadata["capped"] = True

    metadata["atom_count"] = len(kept)
    return kept, metadata


__all__ = ["extract_atoms_from_content", "MAX_ATOMS_PER_CONTENT", "MAX_ATOMS_PER_BATCH"]
