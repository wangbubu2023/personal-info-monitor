"""Backwards-compatible facade for :class:`ContentExtractor`.

Implementation has moved to :mod:`app.domains.ingest.extractor` as part
of Phase 3 step 4 of the module-refactor blueprint. This shim re-exports
the class plus the three private module-level helpers
(``_remove_noise_elements``, ``_find_main_content``,
``_extract_metadata_from_meta_tags``) that existing tests import
directly, plus the ``logger`` so test ``patch`` targets like
``patch("app.processors.extractor.ContentExtractor", ...)`` continue to
resolve. ``api/contents_reader.py`` also keeps a noqa-tagged import
through this shim explicitly as a patch target.

.. deprecated::
   Import :class:`ContentExtractor` from
   :mod:`app.domains.ingest.extractor` directly. This shim will be
   removed in Phase 7.
"""

from app.domains.ingest.extractor import (
    ContentExtractor,
    _extract_metadata_from_meta_tags,
    _find_main_content,
    _remove_noise_elements,
    logger,
)

__all__ = [
    "ContentExtractor",
    "_remove_noise_elements",
    "_find_main_content",
    "_extract_metadata_from_meta_tags",
    "logger",
]
