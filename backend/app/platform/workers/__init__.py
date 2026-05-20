"""Platform-level worker primitives.

Phase 5 step 6 of the refactor relocated the bounded async task queue
out of ``app.tasks`` into the platform layer:

* :mod:`app.platform.workers.queue` — :class:`BoundedTaskQueue`
  (backed by two ``asyncio.Queue`` instances + rotating DLQ log),
  the module-level ``task_queue`` singleton consumed by every
  fetch / ingest dispatch site, and the ``enqueue_fetch`` /
  ``enqueue_ingest_finish`` coroutines. Previously at
  ``app.tasks.task_queue``.

The old ``app.tasks.task_queue`` path remains as a thin re-export shim
so existing test patches continue to resolve. Phase 7 retired the
``enqueue_process`` legacy alias — callers dispatch through
:meth:`BoundedTaskQueue.enqueue_ingest_finish` directly.

Use the canonical singleton path (``app.platform.workers.task_queue``)
for new code and new ``patch`` targets.
"""

from app.platform.workers.queue import (  # noqa: F401 — convenience re-export
    BoundedTaskQueue,
    task_queue,
)

__all__ = ["BoundedTaskQueue", "task_queue"]
