from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest


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

    options = _sync_engine_pool_kwargs(_Settings())

    assert options["pool_size"] == 20
    assert options["max_overflow"] == 10
    assert options["pool_timeout"] == 30
    assert options["pool_pre_ping"] is True


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
