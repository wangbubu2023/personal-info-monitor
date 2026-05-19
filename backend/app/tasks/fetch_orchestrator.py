"""Backwards-compatible re-export.

.. deprecated::
    The canonical home is now :mod:`app.domains.sources.status`. This
    module re-exports the three helpers (``merge_warning_messages``,
    ``set_last_fetch_outcome``, ``persist_fetch_task_exception``) so
    existing import sites — and especially ``unittest.mock.patch``
    targets in the test suite — continue to work. Removal scheduled
    for refactor Phase 7.
"""

from app.domains.sources.status import (  # noqa: F401 — re-export
    merge_warning_messages,
    persist_fetch_task_exception,
    set_last_fetch_outcome,
)

__all__ = [
    "merge_warning_messages",
    "persist_fetch_task_exception",
    "set_last_fetch_outcome",
]
