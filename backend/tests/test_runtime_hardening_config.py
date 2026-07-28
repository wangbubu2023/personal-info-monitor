from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError


def test_sqlite_connections_use_normal_synchronous(tmp_path):
    from app.platform.persistence.database import _set_sqlite_pragma_sync

    conn = sqlite3.connect(tmp_path / "pragma.db")
    try:
        _set_sqlite_pragma_sync(conn, None)
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
    finally:
        conn.close()


def test_sync_pool_scales_with_fetch_concurrency():
    from app.platform.persistence.database import _sync_engine_pool_kwargs

    class _Settings:
        fetch_concurrency = 20
        fetch_active_limit = 20

    options = _sync_engine_pool_kwargs(_Settings())

    assert options["pool_size"] == 20
    assert options["max_overflow"] == 10
    assert options["pool_timeout"] == 30
    assert options["pool_pre_ping"] is True


def test_fetch_concurrency_must_be_positive():
    from app.platform.config.settings import Settings

    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        Settings(_env_file=None, fetch_concurrency=0)


def test_historical_twenty_way_fetch_concurrency_remains_active():
    from app.platform.config.settings import Settings, effective_fetch_concurrency

    settings = Settings(_env_file=None, fetch_concurrency=20)

    assert settings.fetch_concurrency == 20
    assert settings.fetch_active_limit == 20
    assert effective_fetch_concurrency(settings) == 20


def test_fetch_active_limit_can_be_tuned_without_exceeding_configured_concurrency():
    from app.platform.config.settings import Settings, effective_fetch_concurrency

    assert effective_fetch_concurrency(
        Settings(_env_file=None, fetch_concurrency=12, fetch_active_limit=6)
    ) == 6
    assert effective_fetch_concurrency(
        Settings(_env_file=None, fetch_concurrency=3, fetch_active_limit=6)
    ) == 3


def test_async_sqlite_pool_is_bounded():
    from app.platform.persistence.database import _ASYNC_DB_CONCURRENCY, async_engine

    assert async_engine.pool.size() == _ASYNC_DB_CONCURRENCY
    assert async_engine.pool._max_overflow == 0
    assert async_engine.pool._timeout == 30


def test_alembic_revision_file_template_is_date_prefixed():
    ini_text = Path("alembic.ini").read_text(encoding="utf-8")

    assert "file_template = %%(year)d%%(month).2d%%(day).2d_%%(rev)s_%%(slug)s" in ini_text


@pytest.mark.asyncio
async def test_event_loop_observability_sets_slow_callback_threshold():
    from app.platform.runtime.lifespan import _configure_event_loop_observability

    class _Settings:
        event_loop_slow_callback_seconds = 0.123
        event_loop_lag_probe_interval_seconds = 5.0

    loop = asyncio.get_running_loop()
    original_debug = loop.get_debug()
    original_threshold = loop.slow_callback_duration

    task = _configure_event_loop_observability(_Settings())
    try:
        assert task is not None
        assert loop.get_debug() is True
        assert loop.slow_callback_duration == 0.123
    finally:
        if task is not None:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        loop.set_debug(original_debug)
        loop.slow_callback_duration = original_threshold


@pytest.mark.asyncio
async def test_async_sqlite_write_does_not_acquire_threading_writer_lock(
    async_session_factory,
    monkeypatch,
):
    from app.models.system_setting import SystemSetting
    from app.platform.persistence.write_queue import sqlite_write_coordinator

    def fail_if_acquired():
        raise AssertionError("async SQLite writes must not block on the threading writer lock")

    monkeypatch.setattr(sqlite_write_coordinator, "acquire", fail_if_acquired)

    async with async_session_factory() as session:
        session.add(SystemSetting(key="async-writer-regression", value={"ok": True}))
        await session.commit()
