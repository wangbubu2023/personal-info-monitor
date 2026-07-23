"""Reproducible Local single-writer capacity check.

Creates an isolated SQLite database, inserts content-shaped records from
concurrent producers through the process-wide writer coordinator, and prints a
JSON report. No application/user database is touched.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from time import perf_counter

from app.platform.persistence.write_queue import sqlite_write_coordinator


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * percentile))
    return round(ordered[index], 3)


def run_benchmark(
    database_path: Path,
    *,
    records: int,
    sources: int,
    producers: int,
    batch_size: int,
) -> dict[str, object]:
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;
        PRAGMA busy_timeout=5000;
        CREATE TABLE contents (
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX ix_contents_source_created ON contents(source_id, created_at, id);
        """
    )
    connection.close()

    batches = [
        (start, min(records, start + batch_size))
        for start in range(0, records, batch_size)
    ]
    lock_wait_ms: list[float] = []
    transaction_ms: list[float] = []
    busy_errors = 0

    def write_batch(bounds: tuple[int, int]) -> int:
        nonlocal busy_errors
        start, stop = bounds
        wait_started = perf_counter()
        transaction_started = sqlite_write_coordinator.acquire()
        lock_wait_ms.append((transaction_started - wait_started) * 1000)
        conn = sqlite3.connect(database_path, timeout=5)
        try:
            conn.executemany(
                "INSERT INTO contents(id,source_id,title,payload,created_at) VALUES(?,?,?,?,?)",
                [
                    (
                        index + 1,
                        (index % sources) + 1,
                        f"content-{index}",
                        json.dumps({"index": index, "diagnostic": "x" * 64}),
                        "2026-07-23T00:00:00",
                    )
                    for index in range(start, stop)
                ],
            )
            conn.commit()
            return stop - start
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                busy_errors += 1
            raise
        finally:
            conn.close()
            transaction_ms.append((perf_counter() - transaction_started) * 1000)
            sqlite_write_coordinator.release(transaction_started)

    started = perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, producers)) as executor:
        inserted = sum(executor.map(write_batch, batches))
    duration = perf_counter() - started
    conn = sqlite3.connect(database_path)
    try:
        persisted = conn.execute("SELECT count(*) FROM contents").fetchone()[0]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    return {
        "records_requested": records,
        "records_inserted": inserted,
        "records_persisted": persisted,
        "sources": sources,
        "producers": producers,
        "batch_size": batch_size,
        "duration_seconds": round(duration, 3),
        "throughput_records_per_second": round(inserted / duration, 1),
        "lock_wait_ms": {
            "p50": _percentile(lock_wait_ms, 0.50),
            "p95": _percentile(lock_wait_ms, 0.95),
            "p99": _percentile(lock_wait_ms, 0.99),
        },
        "transaction_ms": {
            "p50": _percentile(transaction_ms, 0.50),
            "p95": _percentile(transaction_ms, 0.95),
            "p99": _percentile(transaction_ms, 0.99),
        },
        "busy_errors": busy_errors,
        "integrity_check": integrity,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=100_000)
    parser.add_argument("--sources", type=int, default=500)
    parser.add_argument("--producers", type=int, default=16)
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--database")
    args = parser.parse_args()
    if args.database:
        path = Path(args.database).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        report = run_benchmark(
            path,
            records=max(1, args.records),
            sources=max(1, args.sources),
            producers=max(1, args.producers),
            batch_size=max(1, args.batch_size),
        )
    else:
        with TemporaryDirectory(prefix="pim-m1-sqlite-") as directory:
            report = run_benchmark(
                Path(directory) / "benchmark.db",
                records=max(1, args.records),
                sources=max(1, args.sources),
                producers=max(1, args.producers),
                batch_size=max(1, args.batch_size),
            )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["records_inserted"] == report["records_persisted"] and report["busy_errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
