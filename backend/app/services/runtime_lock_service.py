"""Backwards-compatible re-export.

.. deprecated::
    The canonical home for the DB-backed runtime lock service is now
    :mod:`app.platform.locks.runtime_lock`. Phase 2 step 1 of the
    module refactor moved the implementation out of ``app.services`` so
    ``app.background`` no longer has to depend on a business-services
    module (蓝图 §1.4 / §10).

    This file remains as a thin re-export shim so existing imports
    continue to work; Phase 7 removes it.
"""

from app.platform.locks.runtime_lock import (  # noqa: F401 — re-export
    RuntimeLockService,
    runtime_lock_service,
)

__all__ = ["RuntimeLockService", "runtime_lock_service"]
