"""Backwards-compatible re-export.

.. deprecated::
    The canonical catalog has moved to
    :mod:`app.domains.sources.source_types` as part of Phase 1 of the
    module refactor. This shim keeps existing imports
    (``from app.data.source_types import …``) working and is slated for
    removal in Phase 7.
"""

from app.domains.sources.source_types import (  # noqa: F401 — re-export
    SourceTypeInfo,
    source_type_catalog,
    source_type_label,
)

__all__ = ["SourceTypeInfo", "source_type_catalog", "source_type_label"]
