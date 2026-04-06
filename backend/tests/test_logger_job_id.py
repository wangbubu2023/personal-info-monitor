# backend/tests/test_logger_job_id.py
import asyncio
import logging
import pytest
from app.utils.logger import bind_job_id, restore_job_id, get_job_id, get_logger


@pytest.fixture(autouse=True)
def clean_job_id():
    """Reset job_id ContextVar before each test."""
    restore_token = bind_job_id(None)  # set to None
    yield
    restore_job_id(restore_token)


def test_set_and_get_job_id():
    token = bind_job_id("abc123")
    assert get_job_id() == "abc123"
    restore_job_id(token)
    assert get_job_id() is None


def test_job_id_appears_in_json_log(caplog):
    token = bind_job_id("job-xyz")
    logger = get_logger("test.job")
    with caplog.at_level(logging.INFO, logger="test.job"):
        logger.info("hello from job")
    restore_job_id(token)
    assert any(getattr(r, "job_id", None) == "job-xyz" for r in caplog.records)


def test_job_id_absent_when_not_set(caplog):
    # autouse fixture ensures it's None
    logger = get_logger("test.nojob")
    with caplog.at_level(logging.INFO, logger="test.nojob"):
        logger.info("no job here")
    assert all(getattr(r, "job_id", None) is None for r in caplog.records)


@pytest.mark.asyncio
async def test_concurrent_tasks_have_isolated_job_ids():
    """Two concurrent asyncio tasks must not share job_id ContextVar."""
    results = {}

    async def task_a():
        token = bind_job_id("job-A")
        await asyncio.sleep(0)  # yield to let task_b run
        results["a"] = get_job_id()
        restore_job_id(token)

    async def task_b():
        token = bind_job_id("job-B")
        await asyncio.sleep(0)
        results["b"] = get_job_id()
        restore_job_id(token)

    await asyncio.gather(asyncio.create_task(task_a()), asyncio.create_task(task_b()))
    assert results["a"] == "job-A"
    assert results["b"] == "job-B"
