"""In-process metrics helpers for lightweight observability.

Metrics collected here are process-local and monotonic counters/gauges.
They are exposed in two surfaces:

* JSON ``GET /api/system/metrics`` — snapshot-style aggregates used by the
  dashboard.
* Prometheus ``GET /metrics`` — counters/gauges in Prometheus text format.

Counters in the Prometheus surface are suitable for ``rate()`` / ``irate()``
queries in Grafana; see ``docs/API_GUIDE.md`` for the recommended queries.

Persistence: because the counters live in memory they would reset on every
process restart, which makes ``increase()`` / ``rate()`` queries noisy. To
mitigate that we checkpoint the counters to a JSON file in ``data_dir`` on
graceful shutdown and reload them on startup — see :func:`persist_metrics`
and :func:`restore_metrics`. Restarts still cause a small, one-sample gap,
but the cumulative counts survive.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict, deque
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional


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

    def to_persisted_dict(self) -> Dict[str, Any]:
        """Serialise counter state (drop durations; they're a rolling window)."""
        with self._lock:
            return {
                "fetch_counts": dict(self._fetch_counts),
                "fetch_failures": dict(self._fetch_failures),
                "process_counts": dict(self._process_counts),
                "process_failures": dict(self._process_failures),
            }

    def restore_from_dict(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return
        with self._lock:
            self._fetch_counts = defaultdict(int, {k: int(v) for k, v in (data.get("fetch_counts") or {}).items()})
            self._fetch_failures = defaultdict(int, {k: int(v) for k, v in (data.get("fetch_failures") or {}).items()})
            self._process_counts = defaultdict(int, {k: int(v) for k, v in (data.get("process_counts") or {}).items()})
            self._process_failures = defaultdict(int, {k: int(v) for k, v in (data.get("process_failures") or {}).items()})


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

    def to_persisted_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "total_requests": self._total_requests,
                "total_latency_ms": self._total_latency_ms,
                "max_latency_ms": self._max_latency_ms,
                "by_status": dict(self._by_status),
                "by_route": dict(self._by_route),
            }

    def restore_from_dict(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return
        with self._lock:
            self._total_requests = int(data.get("total_requests") or 0)
            self._total_latency_ms = float(data.get("total_latency_ms") or 0.0)
            self._max_latency_ms = float(data.get("max_latency_ms") or 0.0)
            self._by_status = Counter({k: int(v) for k, v in (data.get("by_status") or {}).items()})
            self._by_route = Counter({k: int(v) for k, v in (data.get("by_route") or {}).items()})


class TaskQueueMetrics:
    """Dropped-task counters for the bounded fetch/process queues."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._dropped: Counter = Counter()

    def record_dropped(self, task_type: str) -> None:
        with self._lock:
            self._dropped[task_type] += 1

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._dropped)

    def prometheus_snapshot(self) -> str:
        with self._lock:
            lines = [
                "# HELP pim_tasks_dropped_total Tasks dropped because the queue was full.",
                "# TYPE pim_tasks_dropped_total counter",
            ]
            if self._dropped:
                for task_type, count in sorted(self._dropped.items()):
                    lines.append(
                        f'pim_tasks_dropped_total{{task_type="{_escape_prometheus_label(task_type)}"}} {count}'
                    )
            else:
                # Emit zero metrics so Prometheus knows the series exist.
                for task_type in ("fetch", "process"):
                    lines.append(f'pim_tasks_dropped_total{{task_type="{task_type}"}} 0')
            return "\n".join(lines) + "\n"

    def to_persisted_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {"dropped": dict(self._dropped)}

    def restore_from_dict(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return
        with self._lock:
            self._dropped = Counter({k: int(v) for k, v in (data.get("dropped") or {}).items()})


class StorageMetrics:
    """Conservation totals plus rolling storage failures for 5m/1h/24h views."""

    _WINDOWS = {"5m": 5 * 60, "1h": 60 * 60, "24h": 24 * 60 * 60}

    def __init__(self) -> None:
        self._lock = Lock()
        self._totals: Counter = Counter()
        self._failure_events: deque[tuple[float, str]] = deque()

    def _purge(self, now: float) -> None:
        cutoff = now - self._WINDOWS["24h"]
        while self._failure_events and self._failure_events[0][0] < cutoff:
            self._failure_events.popleft()

    def record_batch(
        self,
        *,
        requested: int,
        saved: int,
        updated: int,
        unchanged: int,
        failure_classes: list[str],
        outcome: str,
    ) -> None:
        now = time.time()
        with self._lock:
            self._totals.update(
                {
                    "batches": 1,
                    "requested": requested,
                    "saved": saved,
                    "updated": updated,
                    "unchanged": unchanged,
                    "failed": len(failure_classes),
                    f"outcome:{outcome}": 1,
                }
            )
            for failure_class in failure_classes:
                kind = str(failure_class or "unknown")
                self._totals[f"failure:{kind}"] += 1
                self._failure_events.append((now, kind))
            self._purge(now)

    def snapshot(self) -> dict[str, object]:
        now = time.time()
        with self._lock:
            self._purge(now)
            windows: dict[str, dict[str, int]] = {}
            for name, seconds in self._WINDOWS.items():
                counts = Counter(kind for timestamp, kind in self._failure_events if timestamp >= now - seconds)
                windows[name] = dict(counts)
            return {"totals": dict(self._totals), "failure_windows": windows}

    def prometheus_snapshot(self) -> str:
        snapshot = self.snapshot()
        totals = snapshot["totals"]
        lines = [
            "# HELP pim_storage_items_total Storage result items by outcome.",
            "# TYPE pim_storage_items_total counter",
        ]
        for name in ("requested", "saved", "updated", "unchanged", "failed"):
            lines.append(f'pim_storage_items_total{{result="{name}"}} {totals.get(name, 0)}')
        for window, counts in snapshot["failure_windows"].items():
            for failure_class, count in sorted(counts.items()):
                lines.append(
                    f'pim_storage_failures_window{{window="{window}",failure_class="{_escape_prometheus_label(failure_class)}"}} {count}'
                )
        return "\n".join(lines) + "\n"

    def to_persisted_dict(self) -> Dict[str, Any]:
        with self._lock:
            self._purge(time.time())
            return {"totals": dict(self._totals), "failure_events": list(self._failure_events)}

    def restore_from_dict(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return
        with self._lock:
            self._totals = Counter({k: int(v) for k, v in (data.get("totals") or {}).items()})
            self._failure_events = deque(
                (float(timestamp), str(kind))
                for timestamp, kind in (data.get("failure_events") or [])
            )
            self._purge(time.time())


class WindowedReliabilityMetrics:
    """Bounded reliability events for 5m/1h/24h/7d operational views."""

    _WINDOWS = {"5m": 300, "1h": 3600, "24h": 86400, "7d": 604800}

    def __init__(self) -> None:
        self._lock = Lock()
        self._events: deque[tuple[float, str, float]] = deque()

    def record(self, name: str, value: float = 1.0) -> None:
        now = time.time()
        with self._lock:
            self._events.append((now, str(name), float(value)))
            self._purge(now)

    def _purge(self, now: float) -> None:
        cutoff = now - self._WINDOWS["7d"]
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * percentile)))
        return round(ordered[index], 3)

    def snapshot(self) -> dict[str, dict[str, object]]:
        now = time.time()
        with self._lock:
            self._purge(now)
            result: dict[str, dict[str, object]] = {}
            for window, seconds in self._WINDOWS.items():
                grouped: dict[str, list[float]] = defaultdict(list)
                for timestamp, name, value in self._events:
                    if timestamp >= now - seconds:
                        grouped[name].append(value)
                result[window] = {
                    name: {
                        "count": len(values),
                        "sum": round(sum(values), 3),
                        "p50": self._percentile(values, 0.50),
                        "p95": self._percentile(values, 0.95),
                        "p99": self._percentile(values, 0.99),
                    }
                    for name, values in sorted(grouped.items())
                }
            return result

    def prometheus_snapshot(self) -> str:
        lines = [
            "# HELP pim_reliability_window_count Reliability events in a rolling window.",
            "# TYPE pim_reliability_window_count gauge",
        ]
        for window, events in self.snapshot().items():
            for name, values in events.items():
                lines.append(
                    f'pim_reliability_window_count{{window="{window}",event="{_escape_prometheus_label(name)}"}} '
                    f'{values["count"]}'
                )
                lines.append(
                    f'pim_reliability_window_p95{{window="{window}",event="{_escape_prometheus_label(name)}"}} '
                    f'{values["p95"]}'
                )
        return "\n".join(lines) + "\n"

    def to_persisted_dict(self) -> Dict[str, Any]:
        with self._lock:
            self._purge(time.time())
            return {"events": list(self._events)}

    def restore_from_dict(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return
        with self._lock:
            self._events = deque(
                (float(timestamp), str(name), float(value))
                for timestamp, name, value in (data.get("events") or [])
            )
            self._purge(time.time())


request_metrics = RequestMetrics()
source_metrics = SourceMetrics()
task_queue_metrics = TaskQueueMetrics()
storage_metrics = StorageMetrics()
reliability_metrics = WindowedReliabilityMetrics()


# ---------------------------------------------------------------------------
# Persistence helpers.
# ---------------------------------------------------------------------------


_PERSIST_FILENAME = "metrics-checkpoint.json"


def _resolve_persist_path(override: Optional[str | os.PathLike[str]] = None) -> Path:
    if override is not None:
        return Path(override)
    from app.platform.config.settings import get_settings

    data_dir = Path(get_settings().data_dir).expanduser().resolve()
    return data_dir / _PERSIST_FILENAME


def persist_metrics(path: Optional[str | os.PathLike[str]] = None) -> Optional[Path]:
    """Checkpoint module-level metric singletons to JSON on graceful shutdown.

    Returns the file path on success, or ``None`` if persistence was skipped.
    Failures are intentionally swallowed — metrics are an observability aid,
    not a correctness requirement for the app itself.
    """
    try:
        target = _resolve_persist_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 3,
            "request": request_metrics.to_persisted_dict(),
            "source": source_metrics.to_persisted_dict(),
            "task_queue": task_queue_metrics.to_persisted_dict(),
            "storage": storage_metrics.to_persisted_dict(),
            "reliability": reliability_metrics.to_persisted_dict(),
        }
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)
        return target
    except Exception:  # noqa: BLE001 - observability best-effort
        return None


def restore_metrics(path: Optional[str | os.PathLike[str]] = None) -> bool:
    """Restore counters from the JSON checkpoint. Returns True on success."""
    try:
        target = _resolve_persist_path(path)
        if not target.is_file():
            return False
        raw = target.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return False
        request_metrics.restore_from_dict(data.get("request") or {})
        source_metrics.restore_from_dict(data.get("source") or {})
        task_queue_metrics.restore_from_dict(data.get("task_queue") or {})
        storage_metrics.restore_from_dict(data.get("storage") or {})
        reliability_metrics.restore_from_dict(data.get("reliability") or {})
        return True
    except Exception:  # noqa: BLE001 - observability best-effort
        return False
