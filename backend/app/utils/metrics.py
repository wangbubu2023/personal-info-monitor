"""Backwards-compatible re-export.

.. deprecated::
    The canonical home for in-process metrics counters
    (``SourceMetrics`` / ``RequestMetrics`` / ``TaskQueueMetrics``
    singletons and the JSON-checkpoint ``persist_metrics`` /
    ``restore_metrics`` helpers) is now
    :mod:`app.platform.observability.metrics`. Phase 5 step 5 of
    the module refactor moved the implementation out of
    ``app.utils`` because metrics are cross-cutting observability
    infrastructure, not a generic utility.

    This file remains as a thin re-export shim. The modules that
    currently consume ``app.utils.metrics`` (including
    ``app.scheduler`` and ``app.main`` for ``persist_metrics`` /
    ``restore_metrics`` and ``tests/test_metrics_persistence.py``)
    continue to import via this shim path; bulk migration is
    deferred to Phase 7. New code MUST import from
    :mod:`app.platform.observability.metrics` directly.
"""

from app.platform.observability.metrics import *  # noqa: F401,F403 — re-export
from app.platform.observability.metrics import (  # noqa: F401 — explicit (private helpers / state)
    _PERSIST_FILENAME,
    _escape_prometheus_label,
    _resolve_persist_path,
)
