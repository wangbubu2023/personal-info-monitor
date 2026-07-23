"""Tests for metrics checkpointing (:mod:`app.utils.metrics`)."""

from __future__ import annotations

import json

from app.utils.metrics import (
    persist_metrics,
    request_metrics,
    restore_metrics,
    source_metrics,
    storage_metrics,
    task_queue_metrics,
)


def _reset_metrics() -> None:
    request_metrics.restore_from_dict({})
    source_metrics.restore_from_dict({})
    task_queue_metrics.restore_from_dict({})
    storage_metrics.restore_from_dict({})


def test_persist_and_restore_roundtrip(tmp_path):
    _reset_metrics()
    request_metrics.record(method="GET", path="/api/x", status_code=200, duration_ms=12.5)
    request_metrics.record(method="POST", path="/api/y", status_code=500, duration_ms=55.0)
    source_metrics.record_fetch("src-1", duration=0.2, success=True)
    source_metrics.record_fetch("src-1", duration=0.3, success=False)
    source_metrics.record_process("src-1", success=True)
    task_queue_metrics.record_dropped("fetch")
    storage_metrics.record_batch(
        requested=10,
        saved=6,
        updated=1,
        unchanged=2,
        failure_classes=["database"],
        outcome="partial_failure",
    )

    target = tmp_path / "metrics.json"
    written = persist_metrics(target)
    assert written == target
    assert target.is_file()

    _reset_metrics()
    assert request_metrics.snapshot()["http"]["total_requests"] == 0

    assert restore_metrics(target) is True
    http = request_metrics.snapshot()["http"]
    assert http["total_requests"] == 2
    assert http["status_buckets"] == {"2xx": 1, "5xx": 1}
    src = source_metrics.snapshot()["src-1"]
    assert src["fetch_total"] == 2
    assert src["fetch_failures"] == 1
    assert src["process_total"] == 1
    assert task_queue_metrics.snapshot() == {"fetch": 1}
    storage = storage_metrics.snapshot()
    assert storage["totals"]["requested"] == 10
    assert storage["failure_windows"]["5m"] == {"database": 1}


def test_restore_missing_file_returns_false(tmp_path):
    assert restore_metrics(tmp_path / "does-not-exist.json") is False


def test_restore_handles_corrupt_json(tmp_path):
    target = tmp_path / "metrics.json"
    target.write_text("not valid json")
    assert restore_metrics(target) is False


def test_restore_ignores_non_dict_payload(tmp_path):
    target = tmp_path / "metrics.json"
    target.write_text(json.dumps([1, 2, 3]))
    assert restore_metrics(target) is False
