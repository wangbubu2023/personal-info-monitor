from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import verify_api_key
from app.database import Base, get_async_db
from app.main import app


@pytest.fixture(autouse=True)
def _test_default_ai_settings(monkeypatch):
    """Tests must not inherit a developer's .env that disables AI (breaks processor unit tests)."""
    monkeypatch.setenv("AI_PROCESSING_ENABLED", "true")
    monkeypatch.setenv("AI_DAILY_TOKEN_BUDGET", "0")
    # Phase 4 step 8: pin ENRICH_* feature toggles to their default-on state so unit
    # tests can rely on summarizer/translator behavior regardless of the developer
    # shell env. Pre-stash _PIM_AI_DEPRECATION_LOGGED so each Settings() rebuild
    # doesn't spam DeprecationWarning during cache_clear loops.
    monkeypatch.setenv("ENRICH_AUTO_ON_INGEST", "false")
    monkeypatch.setenv("ENRICH_SUMMARY_ENABLED", "true")
    monkeypatch.setenv("ENRICH_TRANSLATE_ENABLED", "true")
    monkeypatch.setenv("_PIM_AI_DEPRECATION_LOGGED", "1")
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture
async def async_session_factory(tmp_path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    db_path = tmp_path / "test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        yield session_factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(
    async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    async def override_get_async_db() -> AsyncIterator[AsyncSession]:
        async with async_session_factory() as session:
            yield session

    # Background tasks (e.g. post-create probe) open their own sessions via
    # AsyncSessionLocal — point them at the same in-memory test DB.
    monkeypatch.setattr("app.database.AsyncSessionLocal", async_session_factory)

    app.dependency_overrides[get_async_db] = override_get_async_db
    app.dependency_overrides[verify_api_key] = lambda: "test-api-key"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client

    app.dependency_overrides.clear()
