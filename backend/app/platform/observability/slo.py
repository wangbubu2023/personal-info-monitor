"""Small in-process SLO ledger used by the M6 release gate and operator API."""

from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
import time


SLO_BUDGETS = {
    "http_p95_ms": 2_000,
    "fetch_p95_ms": 30_000,
    "postprocess_success_rate": 0.99,
    "outbox_delivery_success_rate": 0.99,
    "scheduler_missed_runs": 0,
}


class SLOLedger:
    def __init__(self):
        self._lock = Lock()
        self._latencies: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=2_000))
        self._totals: dict[str, int] = defaultdict(int)
        self._successes: dict[str, int] = defaultdict(int)
        self._missed_runs = 0

    def record(self, component: str, *, latency_ms: float | None = None, success: bool = True) -> None:
        with self._lock:
            self._totals[component] += 1
            if success:
                self._successes[component] += 1
            if latency_ms is not None:
                self._latencies[component].append(max(0.0, float(latency_ms)))

    def record_missed_run(self) -> None:  # noqa: V105
        with self._lock:
            self._missed_runs += 1

    def snapshot(self) -> dict:
        with self._lock:
            components = {}
            for component in sorted(set(self._totals) | set(self._latencies)):
                values = sorted(self._latencies.get(component, ()))
                p95 = values[min(len(values) - 1, int(len(values) * 0.95))] if values else None
                total = self._totals.get(component, 0)
                components[component] = {
                    "total": total,
                    "success": self._successes.get(component, 0),
                    "success_rate": round(self._successes.get(component, 0) / total, 4) if total else None,
                    "p95_ms": round(p95, 2) if p95 is not None else None,
                }
            violations = []
            if components.get("http", {}).get("p95_ms") is not None and components["http"]["p95_ms"] > SLO_BUDGETS["http_p95_ms"]:
                violations.append("http_p95_ms")
            if components.get("fetch", {}).get("p95_ms") is not None and components["fetch"]["p95_ms"] > SLO_BUDGETS["fetch_p95_ms"]:
                violations.append("fetch_p95_ms")
            if components.get("postprocess", {}).get("success_rate") is not None and components["postprocess"]["success_rate"] < SLO_BUDGETS["postprocess_success_rate"]:
                violations.append("postprocess_success_rate")
            return {"budgets": dict(SLO_BUDGETS), "components": components, "missed_scheduler_runs": self._missed_runs, "violations": violations}


slo_ledger = SLOLedger()


def record_latency(component: str, started_at: float, *, success: bool = True) -> None:  # noqa: V103
    slo_ledger.record(component, latency_ms=(time.perf_counter() - started_at) * 1000, success=success)
