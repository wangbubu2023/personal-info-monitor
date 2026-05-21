"""End-to-end async extraction pipeline."""

from __future__ import annotations

from typing import Any

from app.ai.provider import ModelProviderClient, get_runtime_from_system_settings
from app.domains.atoms.extractor.llm_extract import build_extraction_prompt, parse_llm_atoms
from app.domains.atoms.extractor.sentence_split import batch_sentences, split_sentences
from app.domains.atoms.types import AtomCreate
from app.models import Content
from app.utils.logger import get_logger

logger = get_logger(__name__)

_EXTRACTOR_VERSION = 1
_MIN_BODY_LEN = 50


def _article_text(content: Content) -> str:
    parts = [
        (content.title or "").strip(),
        (content.full_content or "").strip(),
        (content.summary or "").strip(),
    ]
    return "\n".join(p for p in parts if p)


async def extract_atoms_from_content(content: Content) -> tuple[list[AtomCreate], dict[str, Any]]:
    """Run LLM extraction for one Content row.

    Returns ``(atoms, metadata)``; empty list when no runtime or no extractable text.
    """
    body = _article_text(content)
    metadata: dict[str, Any] = {
        "extractor": "llm-v1",
        "extractor_version": _EXTRACTOR_VERSION,
        "sentence_count": 0,
        "atom_count": 0,
        "llm_model": None,
        "skipped_reason": None,
    }

    if len(body) < _MIN_BODY_LEN:
        metadata["skipped_reason"] = "body_too_short"
        return [], metadata

    sentences = split_sentences(body)
    metadata["sentence_count"] = len(sentences)
    if not sentences:
        metadata["skipped_reason"] = "no_sentences"
        return [], metadata

    runtime = await get_runtime_from_system_settings(
        setting_key="ai_model",
        default_provider="ollama",
        default_model="",
        default_api_base="http://localhost:11434",
        default_temperature=0.1,
        default_max_tokens=4000,
    )
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

    client = ModelProviderClient()
    collected: list[AtomCreate] = []
    seen_keys: set[tuple[str, str]] = set()

    for batch in batch_sentences(sentences):
        system, user = build_extraction_prompt(
            sentences=batch,
            article_title=content.title or "",
            carrier_source=carrier or "未知",
        )
        try:
            raw = await client.generate_text(
                runtime,
                prompt=user,
                system_prompt=system,
                temperature=0.1,
                max_tokens=4000,
                timeout_seconds=120.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("atom LLM batch failed for content %s: %s", content.id, exc)
            continue

        if not raw:
            continue

        for atom in parse_llm_atoms(
            raw,
            content_id=str(content.id),
            source_url=content.original_url or "",
            full_text=body,
        ):
            key = (atom.source_sentence, atom.atom_type.value)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            collected.append(atom)

    metadata["atom_count"] = len(collected)
    return collected, metadata


__all__ = ["extract_atoms_from_content"]
