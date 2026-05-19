"""Backwards-compatible facade for :class:`KeywordMatcher`.

Implementation has moved to :mod:`app.domains.ingest.keywords.matcher`
as part of Phase 3 step 4 of the module-refactor blueprint. This shim
re-exports the class plus the module-level constants
(``MAX_REGEX_LENGTH``) and ``logger`` so existing test patches
(``patch("app.processors.keyword_matcher.KeywordMatcher", ...)``) and
external callers (``processors/content_processor.py``,
``tasks/process_tasks.py``, ``pipeline/coordinator.py``) keep working.

.. deprecated::
   Import :class:`KeywordMatcher` from
   :mod:`app.domains.ingest.keywords.matcher` directly. This shim will
   be removed in Phase 7.
"""

from app.domains.ingest.keywords.matcher import (  # noqa: F401 — re-export
    MAX_REGEX_LENGTH,
    KeywordMatcher,
    logger,
)

__all__ = ["KeywordMatcher", "MAX_REGEX_LENGTH", "logger"]
