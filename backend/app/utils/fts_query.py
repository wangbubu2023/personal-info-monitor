"""Backwards-compatible facade for the FTS5 query builder.

Implementation has moved to :mod:`app.domains.ingest.search` as part of
Phase 3 step 6 of the module-refactor blueprint. This shim re-exports
:func:`build_sqlite_fts5_match_expression` plus the input-cap constants
so :mod:`app.api.contents_crud` and ``tests/test_fts_query.py`` keep
resolving their imports.

.. deprecated::
   Import directly from :mod:`app.domains.ingest.search`. This shim
   will be removed in Phase 7.
"""

from app.domains.ingest.search import (  # noqa: F401 — re-export
    MAX_FTS_INPUT_CHARS,
    MAX_FTS_TOKENS,
    MAX_TOKEN_LEN,
    build_sqlite_fts5_match_expression,
)

__all__ = [
    "build_sqlite_fts5_match_expression",
    "MAX_FTS_INPUT_CHARS",
    "MAX_FTS_TOKENS",
    "MAX_TOKEN_LEN",
]
