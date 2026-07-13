"""Database connection and session management."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import String, create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator


class UUIDString(TypeDecorator):
    """Store UUIDs as 36-char strings. Accepts both uuid.UUID and str on input."""

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        return value  # keep as string


from app.platform.config.settings import effective_fetch_concurrency, get_settings

settings = get_settings()

_ASYNC_DB_CONCURRENCY = 8


def _sync_engine_pool_kwargs(current_settings) -> dict[str, int | bool]:
    """Size the synchronous pool for fetch and process worker concurrency.

    Fetch workers keep a synchronous ORM session around while a source is
    being collected. SQLAlchemy's SQLite default (5 connections plus 10
    overflow) is therefore smaller than the default 20 fetch workers and can
    block the event loop while waiting for a connection. Keep a small floor
    for low-volume installs and leave overflow headroom for the four process
    workers plus maintenance/API thread work.
    """
    fetch_concurrency = effective_fetch_concurrency(current_settings)
    return {
        "pool_size": max(fetch_concurrency, 10),
        "max_overflow": 10,
        "pool_timeout": 30,
        "pool_pre_ping": True,
    }


# Synchronous engine (for background tasks running in threads)
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    echo=settings.debug,
    **_sync_engine_pool_kwargs(settings),
)

# Asynchronous engine (for FastAPI endpoints). Keep this pool bounded: every
# aiosqlite connection owns a worker thread, while SQLite still serializes
# writes. ``async_session_scope`` below adds an async admission gate so the
# pool never reaches a synchronous checkout timeout under request bursts.
async_engine = create_async_engine(
    settings.async_database_url,
    echo=settings.debug,
    pool_size=_ASYNC_DB_CONCURRENCY,
    max_overflow=0,
    pool_timeout=30,
    pool_pre_ping=True,
)


# SQLite pragmas for performance and correctness
@event.listens_for(engine, "connect")
def _set_sqlite_pragma_sync(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


@event.listens_for(async_engine.sync_engine, "connect")
def _set_sqlite_pragma_async(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


# Session factories
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
AsyncSessionLocal = sessionmaker(
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    bind=async_engine,
    expire_on_commit=False,
)

_async_db_slots = asyncio.Semaphore(_ASYNC_DB_CONCURRENCY)


# Base class for models
class Base(DeclarativeBase):
    pass


def get_db() -> Session:
    """Get synchronous database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@asynccontextmanager
async def async_session_scope() -> AsyncIterator[AsyncSession]:
    """Open a bounded async SQLite session without exhausting the event loop.

    ``aiosqlite`` creates one worker thread per physical connection. The
    default SQLAlchemy pool allows five checked-out connections plus ten
    overflow connections, which can create a burst of worker threads while
    SQLite still serializes writes. Extra callers wait on an asyncio semaphore
    instead of creating more connections or blocking the event loop in the
    pool's timeout path.
    """
    await _async_db_slots.acquire()
    try:
        async with AsyncSessionLocal() as session:
            yield session
    finally:
        _async_db_slots.release()


async def get_async_db() -> AsyncIterator[AsyncSession]:
    """Get asynchronous database session."""
    async with async_session_scope() as session:
        yield session
