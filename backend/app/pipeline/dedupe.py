"""Backwards-compatible facade for :func:`handle_external_id_duplicate`.

Implementation has moved to :mod:`app.domains.ingest.dedupe` as part of
Phase 3 step 2. This shim re-exports the symbol so existing imports and
``unittest.mock.patch("app.pipeline.dedupe.<name>", ...)`` targets keep
working through Phase 7.

.. deprecated::
   Import from :mod:`app.domains.ingest.dedupe` directly.
"""

from app.domains.ingest.dedupe import handle_external_id_duplicate, logger

__all__ = ["handle_external_id_duplicate", "logger"]
