"""Cross-domain contracts owned by the ``fetch`` domain.

A ``FetchBatch`` is the **only** value that the fetch domain emits to
``ingest``. It carries the raw items the collectors produced plus
non-fatal warnings (auth, rate-limit, partial parses…). Ingest then
consumes the batch and produces an :class:`~app.domains.contracts.ingest.IngestResult`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True)
class RawItem:
    """A single raw item produced by a collector.

    ``content`` (plain text) and ``html`` are both optional; ingest decides
    which to keep based on availability and quality scoring. ``metadata``
    is a free-form mapping carried verbatim from the collector (publisher,
    media URLs, Tweet IDs, etc.).
    """

    source_id: str
    title: str
    url: str
    external_id: str | None = None
    content: str | None = None
    html: str | None = None
    publish_time: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FetchWarning:
    """Non-fatal warning emitted by a collector.

    ``code`` is a stable machine identifier (e.g. ``auth_expired``,
    ``rate_limited``, ``partial_html``); ``message`` is human-readable.
    """

    code: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FetchBatch:
    """Aggregated result of a single fetch run for one source."""

    source_id: str
    items: tuple[RawItem, ...] = ()
    warnings: tuple[FetchWarning, ...] = ()


@dataclass(frozen=True)
class FetchOutcome:
    """High-level outcome reported back to ``sources.status``.

    ``status`` is one of ``ok | warning | error``; the other fields are
    optional metadata so callers don't need to peek into the batch.
    """

    source_id: str
    status: str
    fetched_at: datetime
    item_count: int = 0
    new_item_count: int = 0
    warning_message: str | None = None
    error_message: str | None = None
