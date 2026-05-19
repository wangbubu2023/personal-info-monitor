"""Minimal OpenTelemetry compatibility shim.

The 2026-04-20 audit flagged the lack of distributed tracing hooks (O2) as
optional. Instead of pulling the full OpenTelemetry stack into the default
install, we expose a tiny wrapper:

* :func:`get_tracer` always returns something with a ``start_as_current_span``
  context manager, so call-sites stay ``async with tracer.start(...)`` even
  when telemetry is disabled.
* When ``PIM_OTEL_ENABLED`` is truthy **and** the ``opentelemetry-api`` /
  ``opentelemetry-sdk`` packages are importable, the real OTel tracer is
  returned. Otherwise the shim returns a :class:`_NoopTracer` that costs a
  single attribute lookup per span.

Adding real exporters (OTLP, stdout) is intentionally out of scope: that is
an operator decision and usually runs via a sidecar (e.g. the Collector),
configured via the standard ``OTEL_*`` env vars OpenTelemetry already reads
when the real SDK is active. This module's only job is to give us the
*import seam* so future work does not require touching every service call.
"""

from __future__ import annotations

import contextlib
import os
from typing import Any, Iterator


class _NoopSpan:
    """Placeholder span used when OTel is disabled."""

    def set_attribute(self, _key: str, _value: Any) -> None:  # pragma: no cover - trivial
        return None

    def record_exception(self, _exc: BaseException) -> None:  # pragma: no cover - trivial
        return None

    def set_status(self, *_args: Any, **_kwargs: Any) -> None:  # pragma: no cover - trivial
        return None


class _NoopTracer:
    @contextlib.contextmanager
    def start_as_current_span(self, _name: str, **_kwargs: Any) -> Iterator[_NoopSpan]:
        yield _NoopSpan()


def _otel_requested() -> bool:
    return (os.environ.get("PIM_OTEL_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}


_tracer: Any | None = None


def get_tracer(name: str = "pim") -> Any:
    """Return a tracer — real OTel when configured, no-op otherwise.

    The lookup is cached per process, so repeated calls are free. The first
    caller determines the tracer name, which is appropriate: this codebase
    emits all spans under the ``pim`` namespace.
    """
    global _tracer
    if _tracer is not None:
        return _tracer
    if _otel_requested():
        try:
            from opentelemetry import trace  # type: ignore

            _tracer = trace.get_tracer(name)
            return _tracer
        except Exception:  # noqa: BLE001 - never fail on broken/missing OTel install
            pass
    _tracer = _NoopTracer()
    return _tracer
