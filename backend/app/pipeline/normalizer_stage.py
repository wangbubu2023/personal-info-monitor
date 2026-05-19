"""Backwards-compatible facade for :class:`NormalizerStage`.

Implementation has moved to :mod:`app.domains.ingest.normalizer` as part
of Phase 3 step 2. This shim re-exports the class plus the private
helper :func:`_materialize_hydrated_fulltext` that existing tests poke
through ``unittest.mock.patch("app.pipeline.normalizer_stage.<name>", ...)``.

.. deprecated::
   Import :class:`NormalizerStage` from :mod:`app.domains.ingest.normalizer`
   directly. This shim will be removed in Phase 7.
"""

from app.domains.ingest.normalizer import (
    NormalizerStage,
    _materialize_hydrated_fulltext,
    logger,
)

__all__ = [
    "NormalizerStage",
    "_materialize_hydrated_fulltext",
    "logger",
]
