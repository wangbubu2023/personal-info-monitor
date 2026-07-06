"""YAML-backed scoring vocabulary loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

SCORE_VOCAB_PATH = Path(__file__).resolve().parents[2] / "data" / "score_vocab.yaml"

_CACHE: dict[Path, tuple[float, dict[str, Any]]] = {}


def load_score_vocab(path: str | Path | None = None) -> dict[str, Any]:
    """Load score vocabulary data from YAML, caching by mtime."""
    resolved = Path(path or SCORE_VOCAB_PATH).resolve()
    if not resolved.exists():
        return {}

    mtime = resolved.stat().st_mtime
    cached = _CACHE.get(resolved)
    if cached and cached[0] == mtime:
        return cached[1]

    try:
        with resolved.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"failed to parse score vocab YAML: {resolved}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"score vocab YAML must contain a mapping: {resolved}")
    data = dict(raw)
    _CACHE[resolved] = (mtime, data)
    return data


def reload_score_vocab(path: str | Path | None = None) -> dict[str, Any]:
    """Clear cache and reload score vocabulary data from disk."""
    resolved = Path(path or SCORE_VOCAB_PATH).resolve()
    _CACHE.pop(resolved, None)
    return load_score_vocab(resolved)


__all__ = ["SCORE_VOCAB_PATH", "load_score_vocab", "reload_score_vocab"]
