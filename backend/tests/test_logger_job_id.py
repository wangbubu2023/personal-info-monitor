# backend/tests/test_logger_job_id.py
import logging
import pytest
from app.utils.logger import set_job_id, clear_job_id, get_job_id, get_logger


def test_set_and_get_job_id():
    set_job_id("abc123")
    assert get_job_id() == "abc123"
    clear_job_id()
    assert get_job_id() is None


def test_job_id_appears_in_json_log(caplog):
    set_job_id("job-xyz")
    logger = get_logger("test.job")
    with caplog.at_level(logging.INFO, logger="test.job"):
        logger.info("hello from job")
    clear_job_id()
    # caplog captures the record; check the attribute was set
    assert any(getattr(r, "job_id", None) == "job-xyz" for r in caplog.records)


def test_job_id_absent_when_not_set(caplog):
    clear_job_id()
    logger = get_logger("test.nojob")
    with caplog.at_level(logging.INFO, logger="test.nojob"):
        logger.info("no job here")
    assert all(getattr(r, "job_id", None) is None for r in caplog.records)
