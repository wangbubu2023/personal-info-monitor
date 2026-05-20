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

The ``app.utils.logger`` and ``app.utils.metrics`` shims remain
because they still serve as ``patch()`` targets in a number of tests.
The ``app.utils.tracing`` shim was retired by the post-Phase-7 audit
(no remaining callers); the import-boundary checker bans it.
"""
