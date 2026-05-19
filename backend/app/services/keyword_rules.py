"""Backwards-compatible facade for keyword normalization / dedupe / bilingual helpers.

Implementation has moved to :mod:`app.domains.ingest.keywords.rules` as
part of Phase 3 step 4 of the module-refactor blueprint. This shim
re-exports every public symbol plus the private hooks that existing
tests patch (``_translate_keyword_via_public_endpoint``,
``_translation_cache``, ``build_equivalent_terms``).

External callers kept (``api/keywords.py``,
``processors/keyword_matcher`` shim, ``alembic`` migration,
``tests/test_keyword_rules.py``, ``tests/test_api_keywords.py``) all
import through this module, so the patch targets like
``monkeypatch.setattr("app.services.keyword_rules.build_equivalent_terms", …)``
continue to work.

.. deprecated::
   Import directly from :mod:`app.domains.ingest.keywords.rules`. This
   shim will be removed in Phase 7.
"""

from app.domains.ingest.keywords.rules import (  # noqa: F401 — re-export
    _sanitize_equivalent_terms,
    _static_equivalent_terms,
    _translate_keyword_via_public_endpoint,
    _translation_cache,
    build_equivalent_terms,
    compute_stored_equivalent_terms,
    dedupe_keywords_case_insensitive,
    keyword_identity_key,
    logger,
    merge_equivalent_term_lists,
    normalize_keyword_value,
    normalize_manual_equivalent_terms,
)

__all__ = [
    "normalize_keyword_value",
    "keyword_identity_key",
    "dedupe_keywords_case_insensitive",
    "build_equivalent_terms",
    "normalize_manual_equivalent_terms",
    "merge_equivalent_term_lists",
    "compute_stored_equivalent_terms",
    "_translation_cache",
    "_translate_keyword_via_public_endpoint",
    "_sanitize_equivalent_terms",
    "_static_equivalent_terms",
    "logger",
]
