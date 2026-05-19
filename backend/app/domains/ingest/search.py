"""SQLite FTS5 query helpers — sanitize user input before MATCH.

Moved out of ``app.utils.fts_query`` as part of Phase 3 step 6 of the
module-refactor blueprint. FTS read/search belongs to the ingest read
model (it queries the same ``content_fts`` virtual table that ingest
populates via ``StorageStage``).

The legacy ``app.utils.fts_query`` path remains as a re-export shim
through Phase 7 so the only production caller
(``api/contents_crud.py`` lazy import) and the
``tests/test_fts_query.py`` direct imports keep working without
patch-target churn.
"""

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


__all__ = [
    "build_sqlite_fts5_match_expression",
    "MAX_FTS_INPUT_CHARS",
    "MAX_FTS_TOKENS",
    "MAX_TOKEN_LEN",
]
