"""Backwards-compatible re-export.

.. deprecated::
    The canonical home for the bounded async task queue
    (:class:`BoundedTaskQueue` and the ``task_queue`` singleton) is
    now :mod:`app.platform.workers.queue`. Phase 5 step 6 of the
    module refactor moved the implementation out of ``app.tasks``
    because the queue is platform-level worker infrastructure used
    by every dispatch site, not a single business task.

    This file remains as a re-export shim because five call sites
    plus four test patch targets currently import from
    ``app.tasks.task_queue``; a single big-bang rewrite would dwarf
    this slice's risk budget. Phase 7 sweeps the bulk migration.
    New code MUST import from :mod:`app.platform.workers.queue`
    directly.

    Note: ``from ... import *`` does NOT carry underscore-prefixed
    names. The DLQ logger cache (``_dlq_logger``) and helper
    (``_dropped_task_logger``) are re-exported explicitly below so
    monkey-patch / introspection from tests keeps working.
"""

from app.platform.workers.queue import (  # noqa: F401 — re-export
    BoundedTaskQueue,
    LISTING_TRANSLATION_JOB_ID,
    _dlq_logger,
    _dropped_task_logger,
    task_queue,
)

__all__ = ["BoundedTaskQueue", "LISTING_TRANSLATION_JOB_ID", "task_queue"]
