"""Privacy-conscious old/new pipeline comparison payloads."""

from __future__ import annotations

import hashlib
from typing import Any

from .contracts import CleanResult


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def build_shadow_diff(old_body: str, result: CleanResult) -> dict[str, Any]:
    old = str(old_body or "")
    new = result.article_markdown or result.article_text
    return {
        "old_chars": len(old),
        "new_chars": len(new),
        "char_delta": len(new) - len(old),
        "old_hash": _hash(old),
        "new_hash": _hash(new),
        "selected_method": result.extraction_method,
        "quality_status": result.quality_status,
        "quality_score": result.quality_score,
    }
