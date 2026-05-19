"""fetch domain entry point — produce a :class:`FetchBatch` for one Source.

This module exposes :func:`fetch_source_batch`, the single public function
that the rest of the system uses to drive collectors. It accepts the cross-
domain :class:`FetchRequest` contract (no ORM rows) and returns the
:class:`FetchBatch` contract (frozen DTOs only).

**Phase 2 (Blueprint §13.2 step 2):** This first revision is intentionally a
*thin adapter* on top of the legacy :class:`app.pipeline.CollectorStage`. It
exists so callers can start migrating to the contract shape — pipeline /
collector_stage still owns the real execution path. A subsequent step
(blueprint §13.2 step 3+) will invert the dependency: ``CollectorStage``
becomes a backwards-compatible thin wrapper around
``fetch_source_batch`` while the actual fetch + auth + dedupe logic moves
here (and into ``domains/fetch/collectors/`` per collector).

The adapter:

* Resolves the ``SourceSnapshot.source_id`` back to an ORM ``Source`` row
  (we still need ORM for ``auth_config`` relationships and for
  collectors that inject ``_runtime_auth`` onto the row).
* Delegates fetch + auth wiring to ``CollectorStage.execute``.
* Maps the legacy ``(list[dict], merged_warning, primary_warning)`` tuple
  to a frozen :class:`FetchBatch`.
"""

from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID

from sqlalchemy.orm import Session

from app.domains.contracts import FetchBatch, FetchRequest, FetchWarning, RawItem
from app.models import Source
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _coerce_source_id(raw: str) -> Any:
    """Source PKs are UUID-typed at the ORM layer but string-typed in DTOs."""

    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        return raw


def _load_source_or_none(db: Session, source_id: str) -> Source | None:
    pk = _coerce_source_id(source_id)
    return db.query(Source).filter(Source.id == pk).first()


def _item_from_raw(raw: Mapping[str, Any], source_id: str) -> RawItem:
    metadata = raw.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    return RawItem(
        source_id=source_id,
        title=str(raw.get("title") or ""),
        url=str(raw.get("url") or ""),
        external_id=(str(raw["external_id"]) if raw.get("external_id") else None),
        content=(raw.get("content") if isinstance(raw.get("content"), str) else None),
        html=(raw.get("html") if isinstance(raw.get("html"), str) else None),
        publish_time=raw.get("publish_time"),
        metadata=dict(metadata),
    )


def _warnings_tuple(
    merged_warning: str | None,
    primary_warning: tuple[str, str, str] | None,
) -> tuple[FetchWarning, ...]:
    """Build a single-element warning tuple from the legacy stage outputs.

    The legacy stage already merged its internal entries into a single
    user-facing string + a "primary" (code, severity, message) triple.
    We preserve that primary triple here; downstream consumers that need
    the full warning list will get it once collectors are migrated to
    emit ``FetchWarning`` natively.
    """

    if primary_warning:
        code, severity, message = primary_warning
        return (
            FetchWarning(
                code=code,
                message=message,
                details={"severity": severity, "merged": merged_warning or message},
            ),
        )
    if merged_warning:
        return (
            FetchWarning(
                code="fetch_warning",
                message=str(merged_warning),
                details={"severity": "warning"},
            ),
        )
    return ()


async def fetch_source_batch(db: Session, request: FetchRequest) -> FetchBatch:
    """Run a single fetch for ``request.source`` and return its :class:`FetchBatch`.

    Returns an empty batch with a synthetic ``source_missing`` warning when
    the source row cannot be resolved (e.g. it was deleted between
    scheduling and execution). Collector exceptions are not caught here —
    the underlying ``CollectorStage.execute`` already isolates per-URL
    failures and surfaces them through the warning channel.
    """

    source_id = request.source.source_id
    source = _load_source_or_none(db, source_id)
    if source is None:
        logger.warning("fetch_source_batch: source %s not found", source_id)
        return FetchBatch(
            source_id=source_id,
            items=(),
            warnings=(
                FetchWarning(
                    code="source_missing",
                    message=f"Source {source_id} not found",
                    details={"severity": "error"},
                ),
            ),
        )

    # The legacy CollectorStage owns the full fetch + auth + dedupe + filter
    # path today. We import it lazily to avoid pulling pipeline modules at
    # ``app.domains.fetch`` import time (and to make a future inversion of
    # this dependency a single-line change).
    from app.pipeline.collector_stage import CollectorStage

    raw_contents, merged_warning, primary_warning = await CollectorStage.execute(db, source)
    items = tuple(_item_from_raw(item, source_id) for item in raw_contents or ())
    warnings = _warnings_tuple(merged_warning, primary_warning)
    return FetchBatch(source_id=source_id, items=items, warnings=warnings)
