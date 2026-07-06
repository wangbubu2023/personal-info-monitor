"""Projection helpers for score fields stored in content metadata."""

from __future__ import annotations

from typing import Any, Mapping


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def sync_content_score_columns(content: Any, metadata: Mapping[str, Any] | None) -> None:
    """Mirror hot scoring fields from JSON metadata onto indexed columns."""
    meta = metadata if isinstance(metadata, Mapping) else {}
    article_score = _coerce_float(meta.get("article_score"))
    final_score = _coerce_float(meta.get("final_score"))
    content.article_score = article_score if article_score is not None else final_score
    content.final_score = final_score if final_score is not None else article_score
    content.selection_status = str(meta.get("selection_status") or "")[:32] or None
    content.lane = str(meta.get("lane") or "")[:64] or None


__all__ = ["sync_content_score_columns"]
