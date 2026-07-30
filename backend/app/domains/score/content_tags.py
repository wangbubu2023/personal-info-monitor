"""User-facing content tags backed by the canonical Lane vocabulary."""

from __future__ import annotations

from typing import Any

from app.domains.score.score_vocab import VALID_LANES


def effective_content_tags(*, lane: object, metadata: object) -> list[str]:
    meta = metadata if isinstance(metadata, dict) else {}
    manual = meta.get("user_tags")
    if isinstance(manual, list):
        normalized = [
            value
            for value in manual
            if isinstance(value, str) and value in VALID_LANES
        ]
        if normalized:
            return list(dict.fromkeys(normalized))[:4]
    for candidate in (lane, meta.get("lane")):
        if isinstance(candidate, str) and candidate in VALID_LANES:
            return [candidate]
    return []


def content_annotation_context(content: Any) -> dict[str, Any]:
    return {
        "title": content.translated_title or content.title,
        "summary": (content.translated_summary or content.summary or "")[:1200],
        "source_id": str(content.source_id),
    }
