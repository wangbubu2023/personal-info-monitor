"""In-process metrics helpers for lightweight observability."""

from __future__ import annotations

from collections import Counter, defaultdict
from threading import Lock
from typing import Dict


class SourceMetrics:
    """Per-source fetch/process counters, failures, and rolling fetch duration averages."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._fetch_counts: dict[str, int] = defaultdict(int)
        self._fetch_failures: dict[str, int] = defaultdict(int)
        self._fetch_durations: dict[str, list[float]] = defaultdict(list)
        self._process_counts: dict[str, int] = defaultdict(int)
        self._process_failures: dict[str, int] = defaultdict(int)

    def record_fetch(self, source_id: str, duration: float, success: bool) -> None:
        with self._lock:
            self._fetch_counts[source_id] += 1
            if not success:
                self._fetch_failures[source_id] += 1
            durations = self._fetch_durations[source_id]
            durations.append(duration)
            if len(durations) > 100:
                durations[:] = durations[-100:]

    def record_process(self, source_id: str, success: bool) -> None:
        with self._lock:
            self._process_counts[source_id] += 1
            if not success:
                self._process_failures[source_id] += 1

    def snapshot(self) -> dict:
        with self._lock:
            result: dict[str, dict[str, float | int]] = {}
            for sid in set(self._fetch_counts) | set(self._process_counts):
                durations = self._fetch_durations.get(sid, [])
                avg_ms = (sum(durations) / len(durations) * 1000) if durations else 0
                result[sid] = {
                    "fetch_total": self._fetch_counts.get(sid, 0),
                    "fetch_failures": self._fetch_failures.get(sid, 0),
                    "fetch_avg_ms": round(avg_ms, 1),
                    "process_total": self._process_counts.get(sid, 0),
                    "process_failures": self._process_failures.get(sid, 0),
                }
            return result


def _escape_prometheus_label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class RequestMetrics:
    """Thread-safe request counters and latency aggregates."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._total_requests = 0
        self._total_latency_ms = 0.0
        self._max_latency_ms = 0.0
        self._by_status = Counter()
        self._by_route = Counter()

    def record(self, *, method: str, path: str, status_code: int, duration_ms: float) -> None:
        route_key = f"{method.upper()} {path or '/'}"
        status_key = f"{status_code // 100}xx"
        with self._lock:
            self._total_requests += 1
            self._total_latency_ms += max(0.0, duration_ms)
            self._max_latency_ms = max(self._max_latency_ms, duration_ms)
            self._by_status[status_key] += 1
            self._by_route[route_key] += 1

    def snapshot(self) -> Dict[str, object]:
        with self._lock:
            total_requests = self._total_requests
            avg_latency_ms = (
                round(self._total_latency_ms / total_requests, 2)
                if total_requests
                else 0.0
            )
            return {
                "http": {
                    "total_requests": total_requests,
                    "avg_latency_ms": avg_latency_ms,
                    "max_latency_ms": round(self._max_latency_ms, 2),
                    "status_buckets": dict(self._by_status),
                    "top_routes": dict(self._by_route.most_common(20)),
                }
            }

    def prometheus_snapshot(self) -> str:
        with self._lock:
            lines = [
                "# HELP pim_http_requests_total Total HTTP requests handled.",
                "# TYPE pim_http_requests_total counter",
                f"pim_http_requests_total {self._total_requests}",
                "# HELP pim_http_request_latency_ms_total Total request latency in milliseconds.",
                "# TYPE pim_http_request_latency_ms_total counter",
                f"pim_http_request_latency_ms_total {round(self._total_latency_ms, 2)}",
                "# HELP pim_http_request_latency_ms_max Maximum request latency in milliseconds.",
                "# TYPE pim_http_request_latency_ms_max gauge",
                f"pim_http_request_latency_ms_max {round(self._max_latency_ms, 2)}",
            ]

            for status, count in sorted(self._by_status.items()):
                lines.append(
                    f'pim_http_requests_by_status{{status="{_escape_prometheus_label(status)}"}} {count}'
                )
            for route, count in sorted(self._by_route.items()):
                lines.append(
                    f'pim_http_requests_by_route{{route="{_escape_prometheus_label(route)}"}} {count}'
                )
            return "\n".join(lines) + "\n"


request_metrics = RequestMetrics()
source_metrics = SourceMetrics()
