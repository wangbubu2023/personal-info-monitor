"""Cross-domain contracts owned by the ``ingest`` domain."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IngestResult:
    """Result of ingesting a :class:`~app.domains.contracts.fetch.FetchBatch`.

    All counters are non-overlapping; the sum of ``len(saved_content_ids)``,
    ``stale_skipped``, ``duplicate_skipped``, ``build_failed`` and
    ``keyword_filtered`` should equal the input batch's item count.
    """

    source_id: str
    saved_content_ids: tuple[str, ...] = ()
    latest_saved_marker: str | None = None
    stale_skipped: int = 0
    duplicate_skipped: int = 0
    build_failed: int = 0
    keyword_filtered: int = 0


@dataclass(frozen=True)
class FinishContentResult:
    """Result of the non-LLM post-ingest finish step.

    Returned by ``ingest.finish_content`` (currently
    ``process_tasks.process_new_content``) so callers can decide whether to
    enqueue an ``enrich`` job (manual reprocess, summarisation, translation).
    """

    content_id: str
    keyword_matches: int = 0
    quality_passed: bool = True
    reject_reason: str | None = None
