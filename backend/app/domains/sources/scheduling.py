"""Single source of truth for "when is this source due to be fetched".

This module owns the formulas previously hidden inside
``app.tasks.fetch_tasks._effective_due_interval_minutes``. Both the
APScheduler tick (``check_and_fetch_due_sources``) and the read-side
``MonitorService.get_source_status`` agree on the same instant by
calling :func:`next_fetch_at_for` here — otherwise the UI would show
e.g. ``13:53`` while the fetch landed at ``13:56`` for no visible
reason.

Phase 1 of the refactor (see ``PIM 模块化重构实施蓝图 v3 §7``) lifts
this code out of ``app.tasks`` so the ``services``/``api`` layers no
longer have to lazy-import a private symbol from a task module.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Sequence

from sqlalchemy.orm import Session

from app.features import PODCAST_SOURCES_ENABLED
from app.models import Source
from app.models.source import SourceType
from app.utils.datetime import utcnow_naive
from app.utils.human_timing import jittered_interval_minutes


def effective_due_interval_minutes(source: Source) -> float:
    """Base interval × exponential error backoff × ±10% deterministic jitter.

    Formula::

        interval = source.fetch_interval × 2**min(error_count, 5)
                   × jitter(±10%, keyed on (source_id, last_fetched_at))

    The jitter is **deterministic per source-cycle** so multiple call sites
    in the same tick return identical results.
    """
    base = int(source.fetch_interval or 60)
    backoff = 1 << min(int(source.error_count or 0), 5)  # 2**n, capped at 32×
    base_with_backoff = base * backoff
    return jittered_interval_minutes(
        str(source.id),
        base_with_backoff,
        source.last_fetched_at,
        jitter_pct=0.1,
    )


def next_fetch_at_for(source: Source) -> datetime | None:
    """Return the moment ``source`` will become due, or ``None`` if never fetched.

    Returning ``None`` mirrors the existing API contract: a source that
    has not yet been fetched is *immediately* due (the scheduler picks it
    up on the next tick), so there is no meaningful future timestamp to
    show in the UI.
    """
    if source.last_fetched_at is None:
        return None
    interval_minutes = effective_due_interval_minutes(source)
    return source.last_fetched_at + timedelta(minutes=interval_minutes)


def is_due(source: Source, *, now: datetime | None = None) -> bool:
    """Whether ``source`` is currently due for fetching."""
    if source.last_fetched_at is None:
        return True
    next_fetch = next_fetch_at_for(source)
    if next_fetch is None:
        return True
    return (now or utcnow_naive()) >= next_fetch


def list_due_source_ids(
    db: Session,
    *,
    include_podcast: bool | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Return the IDs of all enabled sources whose ``next_fetch_at`` has passed.

    The due check runs in Python (not SQL) so the deterministic per-cycle
    jitter from :func:`effective_due_interval_minutes` applies consistently;
    SQLite cannot hash, and pushing randomness into the query would
    destabilise the due window between ticks.

    ``include_podcast=None`` defers to the ``PODCAST_SOURCES_ENABLED``
    feature flag (the production default); callers may override it for
    tests or feature-flag overrides.
    """
    if include_podcast is None:
        include_podcast = PODCAST_SOURCES_ENABLED
    query = db.query(Source).filter(Source.enabled.is_(True))
    if not include_podcast:
        query = query.filter(Source.type != SourceType.PODCAST)
    now = now or utcnow_naive()
    due: list[str] = []
    for source in query.all():
        if is_due(source, now=now):
            due.append(str(source.id))
    return due


def get_due_sources(
    db: Session,
    *,
    include_podcast: bool | None = None,
    now: datetime | None = None,
) -> list[Source]:
    """Like :func:`list_due_source_ids` but returns the ORM rows.

    Kept as a convenience for ``MonitorService.get_due_sources`` which
    historically returned the rows so the caller can inspect names,
    intervals, etc.
    """
    if include_podcast is None:
        include_podcast = True  # MonitorService never filtered podcasts; preserve.
    query = db.query(Source).filter(Source.enabled.is_(True))
    if not include_podcast:
        query = query.filter(Source.type != SourceType.PODCAST)
    now = now or utcnow_naive()
    return [source for source in query.all() if is_due(source, now=now)]


__all__: Sequence[str] = (
    "effective_due_interval_minutes",
    "next_fetch_at_for",
    "is_due",
    "list_due_source_ids",
    "get_due_sources",
)
