"""Database connection and session management."""

import uuid

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


from app.platform.config.settings import get_settings

settings = get_settings()


def _sync_engine_pool_kwargs(current_settings) -> dict[str, int | bool]:
    """Size the synchronous pool for fetch and process worker concurrency.

    Fetch workers keep a synchronous ORM session around while a source is
    being collected. SQLAlchemy's SQLite default (5 connections plus 10
    overflow) is therefore smaller than the default 20 fetch workers and can
    block the event loop while waiting for a connection. Keep a small floor
    for low-volume installs and leave overflow headroom for the four process
    workers plus maintenance/API thread work.
    """
    fetch_concurrency = max(1, int(current_settings.fetch_concurrency))
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

# Asynchronous engine (for FastAPI endpoints).
# SQLite + aiosqlite: SQLAlchemy's default async pool (``NullPool``-style
# behaviour for sqlite) is appropriate — no TCP connection pool tuning needed.
async_engine = create_async_engine(
    settings.async_database_url,
    echo=settings.debug,
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


async def get_async_db() -> AsyncSession:
    """Get asynchronous database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
