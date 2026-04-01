"""In-process metrics helpers for lightweight observability."""

from __future__ import annotations

from collections import Counter
from threading import Lock
from typing import Dict


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
