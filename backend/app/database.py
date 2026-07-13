"""Backwards-compatible re-export.

.. deprecated::
    The canonical home for SQLAlchemy engines, session factories,
    declarative :class:`Base`, and the FastAPI ``get_async_db`` /
    ``get_db`` dependencies is now
    :mod:`app.platform.persistence.database`. Phase 5 step 4 of the
    module refactor moved the implementation out of ``app`` because
    the database layer is cross-cutting persistence infrastructure,
    not application code.

    This file remains as a re-export shim because over 50 modules
    (API routers, services, tasks, model files, scripts, tests,
    Alembic env) currently import from ``app.database``; a single
    big-bang rewrite would dwarf this slice's risk budget. Phase 7
    (or an opportunistic future PR) can sweep the bulk migration
    once the rest of Phase 5 is settled. New code MUST import from
    :mod:`app.platform.persistence.database` directly.
"""

from app.platform.persistence.database import (  # noqa: F401 — re-export
    AsyncSessionLocal,
    Base,
    SessionLocal,
    UUIDString,
    async_session_scope,
    async_engine,
    engine,
    get_async_db,
    get_db,
    settings,
)
from app.platform.persistence.database import (  # noqa: F401 — explicit; SQLAlchemy event registrations
    _set_sqlite_pragma_async,
    _set_sqlite_pragma_sync,
)

__all__ = [
    "AsyncSessionLocal",
    "Base",
    "SessionLocal",
    "UUIDString",
    "async_engine",
    "async_session_scope",
    "engine",
    "get_async_db",
    "get_db",
]
