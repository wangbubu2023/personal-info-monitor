"""Backwards-compatible facade for :class:`StorageStage`.

Implementation has moved to :mod:`app.domains.ingest.storage` as part of
Phase 3 step 2. This shim re-exports the class plus the module-level
``normalize_external_id`` symbol that existing tests patch through
``unittest.mock.patch("app.pipeline.storage_stage.normalize_external_id", ...)``.

.. deprecated::
   Import :class:`StorageStage` from :mod:`app.domains.ingest.storage`
   directly. This shim will be removed in Phase 7.
"""

from app.domains.ingest.storage import StorageStage, logger, normalize_external_id

__all__ = ["StorageStage", "logger", "normalize_external_id"]
