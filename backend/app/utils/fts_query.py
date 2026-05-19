"""SQLite FTS5 query helpers — sanitize user input before MATCH."""

from __future__ import annotations

import re

# User-facing search string cap (chars)
MAX_FTS_INPUT_CHARS = 200
# Max tokens joined with AND
MAX_FTS_TOKENS = 20
# Per-token length cap after cleaning
MAX_TOKEN_LEN = 64

# Strip FTS5 operator characters; keep double-quotes so we can escape them for phrase syntax.
_FTS_STRIP_CHARS = '*^:()[]{}\\-'
# Whitespace / punctuation split for initial tokenization
_TOKEN_SPLIT = re.compile(r"\S+")


def _clean_token(tok: str) -> str:
    cleaned = tok
    for ch in _FTS_STRIP_CHARS:
        cleaned = cleaned.replace(ch, "")
    return cleaned.strip()[:MAX_TOKEN_LEN]


def build_sqlite_fts5_match_expression(user_input: str) -> str | None:
    """Build a safe FTS5 MATCH expression (AND of quoted phrases).

    Returns None when there are no searchable tokens (caller should skip FTS filter).
    """
    raw = (user_input or "").strip()[:MAX_FTS_INPUT_CHARS]
    if not raw:
        return None

    tokens = _TOKEN_SPLIT.findall(raw)[:MAX_FTS_TOKENS]
    parts: list[str] = []
    for tok in tokens:
        cleaned = _clean_token(tok)
        if not cleaned:
            continue
        # Escape double quotes for FTS5 phrase quoting
        escaped = cleaned.replace('"', '""')
        parts.append(f'"{escaped}"')

    if not parts:
        return None
    return " AND ".join(parts)
