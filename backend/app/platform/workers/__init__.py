"""Platform-level worker primitives.

Phase 5 step 6 of the refactor relocates the bounded async task queue
out of ``app.tasks`` into the platform layer:

* :mod:`app.platform.workers.queue` — :class:`BoundedTaskQueue`
  (backed by two ``asyncio.Queue`` instances + rotating DLQ log),
  the module-level ``task_queue`` singleton consumed by every
  fetch / ingest dispatch site, and the
  ``enqueue_fetch`` / ``enqueue_ingest_finish`` /
  ``enqueue_process`` (legacy alias) coroutines. Previously at
  ``app.tasks.task_queue``.

The old path remains as a re-export shim. The five call sites that
consume the singleton (``app.main``, ``app.tasks.fetch_tasks``,
``app.tasks.process_tasks``, ``app.api.sources.fetch_import``, plus
test_fetch_tasks_extended ``patch`` targets) continue to import via
the shim path; bulk migration is deferred to Phase 7 to keep this
slice small.

Update the canonical singleton path for new code instead of the
shim — and especially for new ``patch`` targets in tests.
"""

from app.platform.workers.queue import (  # noqa: F401 — convenience re-export
    BoundedTaskQueue,
    task_queue,
)

__all__ = ["BoundedTaskQueue", "task_queue"]
