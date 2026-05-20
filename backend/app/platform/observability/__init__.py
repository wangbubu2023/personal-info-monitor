"""Platform-level observability primitives.

Phase 5 step 5 of the refactor relocates cross-cutting telemetry helpers
out of ``app.utils`` into the platform layer:

* :mod:`app.platform.observability.logger` — JSON / human log formatting,
  request- and job-id context binding, rotating file handler, mirror.
  Previously at ``app.utils.logger``.
* :mod:`app.platform.observability.metrics` — Prometheus counters /
  histograms / gauges, DB-backed restore for restart-safe counters,
  ``MetricsRecorder`` test helper. Previously at ``app.utils.metrics``.
* :mod:`app.platform.observability.tracing` — distributed-tracing
  helpers (currently span-id / parent-id generation + ``with_span``
  context manager). Previously at ``app.utils.tracing``.

All three old paths remain as re-export shims (with explicit
underscore-symbol forwarding so existing ``patch("app.utils.metrics._*")``
test sites keep targeting the same module identity). The 77 modules
that currently consume these helpers continue to import via the shim
path; bulk migration is deferred to Phase 7 to keep this slice small.
"""
