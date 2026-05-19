"""Cross-domain contracts owned by the ``sources`` domain.

These DTOs flow **out** of the sources domain into ``fetch`` (so the fetch
collectors never see ORM ``Source`` rows) and into the HTTP layer's status
views.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True)
class SourceSnapshot:
    """Immutable snapshot of a single Source row for cross-domain use.

    Only fields that fetch/ingest/scheduling actually need are exposed; any
    ORM-bound state (relationships, lazy attributes) is deliberately omitted
    so the snapshot is safe to pass across thread/loop boundaries.
    """

    source_id: str
    source_type: str
    name: str
    primary_url: str
    extra_urls: tuple[str, ...] = ()
    fetch_interval_minutes: int = 60
    use_keyword_filter: bool = False
    auth_config_id: str | None = None
    auth_required: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FetchRequest:
    """A single unit of work for the fetch domain.

    ``manual=True`` indicates the request originated from a user-triggered
    fetch (HTTP API or pimctl) — collectors may relax rate-limit / cookie
    freshness checks in that case.
    """

    source: SourceSnapshot
    manual: bool = False
    job_id: str | None = None


@dataclass(frozen=True)
class SourceStatusView:
    """Read-model returned by the sources HTTP layer."""

    source_id: str
    name: str
    status: str
    last_fetch_at: datetime | None = None
    last_success_at: datetime | None = None
    next_fetch_at: datetime | None = None
    error_count: int = 0
    last_error_message: str | None = None
    last_warning_message: str | None = None
