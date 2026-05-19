"""Backwards-compatible facade for the content-quality metadata helpers.

Implementation has moved to :mod:`app.domains.ingest.quality_metadata` as
part of Phase 3 step 4 of the module-refactor blueprint. This shim
re-exports every public symbol — the ``FULLTEXT_STATUS_*`` constants,
:class:`ContentQuality`, :func:`assess_content_quality`,
:func:`merge_content_quality_metadata` — so existing imports
(``processors/content_processor.py``, ``tasks/process_tasks.py``,
``tests/test_content_quality_scoring.py``) keep working.

.. deprecated::
   Import directly from :mod:`app.domains.ingest.quality_metadata`. This
   shim will be removed in Phase 7.
"""

from app.domains.ingest.quality_metadata import (
    FULLTEXT_STATUS_BLOCKED,
    FULLTEXT_STATUS_FULL,
    FULLTEXT_STATUS_PARTIAL,
    FULLTEXT_STATUS_SUMMARY_ONLY,
    FULLTEXT_STATUS_TITLE_ONLY,
    ContentQuality,
    assess_content_quality,
    merge_content_quality_metadata,
)

__all__ = [
    "FULLTEXT_STATUS_BLOCKED",
    "FULLTEXT_STATUS_FULL",
    "FULLTEXT_STATUS_PARTIAL",
    "FULLTEXT_STATUS_SUMMARY_ONLY",
    "FULLTEXT_STATUS_TITLE_ONLY",
    "ContentQuality",
    "assess_content_quality",
    "merge_content_quality_metadata",
]
