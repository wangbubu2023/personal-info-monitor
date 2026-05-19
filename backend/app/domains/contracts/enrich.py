"""Cross-domain contracts owned by the ``enrich`` domain."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnrichRequest:
    """Request emitted by ingest/HTTP to trigger summarisation/translation.

    ``force=True`` re-runs LLM even if a cached summary already exists.
    """

    content_id: str
    summarize: bool = True
    translate: bool = True
    force: bool = False


@dataclass(frozen=True)
class ReprocessRequest:
    """Request for the manual reprocess flow (re-extract + re-summarise).

    ``regenerate_summary`` / ``retranslate`` mirror the existing HTTP query
    parameters on ``POST /api/contents/{id}/reprocess`` so the migration is
    a straight rename.
    """

    content_id: str
    regenerate_summary: bool = False
    retranslate: bool = False
    triggered_by: str = "manual"
