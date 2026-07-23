"""Bounded best-effort JSONL sink for verbose diagnostic records."""

from __future__ import annotations

from collections import deque
from datetime import datetime
import json
from pathlib import Path
from threading import Lock
from typing import Any

from app.platform.observability.metrics import reliability_metrics


class DiagnosticSink:
    """Keep verbose diagnostics out of the core SQLite transaction path."""

    def __init__(
        self,
        directory: str | Path,
        *,
        buffer_max: int = 2000,
        batch_size: int = 100,
        rotate_bytes: int = 10 * 1024 * 1024,
        disk_limit_bytes: int = 100 * 1024 * 1024,
    ) -> None:
        self.directory = Path(directory)
        self.buffer_max = max(1, int(buffer_max))
        self.batch_size = max(1, int(batch_size))
        self.rotate_bytes = max(1024, int(rotate_bytes))
        self.disk_limit_bytes = max(self.rotate_bytes, int(disk_limit_bytes))
        self._buffer: deque[dict[str, Any]] = deque()
        self._lock = Lock()
        self._sequence = 0

    def record(self, category: str, payload: dict[str, Any], *, trace_id: str | None = None) -> bool:
        item = {
            "timestamp": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "category": str(category),
            "trace_id": trace_id,
            "payload": payload,
        }
        with self._lock:
            if len(self._buffer) >= self.buffer_max:
                self._buffer.popleft()
                reliability_metrics.record("diagnostic_dropped")
            self._buffer.append(item)
            should_flush = len(self._buffer) >= self.batch_size
        if should_flush:
            self.flush()
        return True

    def flush(self) -> int:
        with self._lock:
            items = [self._buffer.popleft() for _ in range(min(self.batch_size, len(self._buffer)))]
        if not items:
            return 0
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            target = self._active_path()
            with target.open("a", encoding="utf-8") as handle:
                for item in items:
                    handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
            reliability_metrics.record("diagnostic_flush_records", len(items))
            self._enforce_disk_limit()
            return len(items)
        except (OSError, TypeError, ValueError):
            reliability_metrics.record("diagnostic_flush_failure")
            # Diagnostics are explicitly non-transactional. Do not reinsert a
            # poison record forever; account for the loss and keep business work alive.
            reliability_metrics.record("diagnostic_dropped", len(items))
            return 0

    def close(self) -> int:
        flushed = 0
        while True:
            count = self.flush()
            if count <= 0:
                break
            flushed += count
        return flushed

    def _active_path(self) -> Path:
        target = self.directory / f"diagnostics-{self._sequence:04d}.jsonl"
        if target.exists() and target.stat().st_size >= self.rotate_bytes:
            self._sequence += 1
            target = self.directory / f"diagnostics-{self._sequence:04d}.jsonl"
        return target

    def _enforce_disk_limit(self) -> None:
        files = sorted(
            self.directory.glob("diagnostics-*.jsonl"),
            key=lambda path: path.stat().st_mtime,
        )
        total = sum(path.stat().st_size for path in files)
        for path in files:
            if total <= self.disk_limit_bytes or path == files[-1]:
                break
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            total -= size
            reliability_metrics.record("diagnostic_rotated_bytes", size)


def build_default_diagnostic_sink() -> DiagnosticSink:
    from app.platform.config.settings import get_settings

    settings = get_settings()
    return DiagnosticSink(
        Path(settings.data_dir) / "diagnostics",
        buffer_max=settings.diagnostic_buffer_max,
        batch_size=settings.diagnostic_batch_size,
        rotate_bytes=settings.diagnostic_rotate_bytes,
        disk_limit_bytes=settings.diagnostic_disk_limit_bytes,
    )


__all__ = ["DiagnosticSink", "build_default_diagnostic_sink"]
