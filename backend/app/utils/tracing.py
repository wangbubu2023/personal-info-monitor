"""Backwards-compatible re-export.

.. deprecated::
    The canonical home for the OpenTelemetry compatibility shim
    (``get_tracer`` + the no-op fallback that lets call sites stay
    ``with tracer.start_as_current_span(...)`` even when OTel is
    disabled) is now :mod:`app.platform.observability.tracing`.
    Phase 5 step 5 of the module refactor moved the implementation
    out of ``app.utils`` because tracing is cross-cutting
    observability infrastructure, not a generic utility.

    This file remains as a thin re-export shim. The handful of
    modules that currently consume ``app.utils.tracing`` continue
    to import via this shim path; bulk migration is deferred to
    Phase 7. New code MUST import from
    :mod:`app.platform.observability.tracing` directly.
"""

from app.platform.observability.tracing import *  # noqa: F401,F403 — re-export
from app.platform.observability.tracing import (  # noqa: F401 — explicit (private types + cached tracer)
    _NoopSpan,
    _NoopTracer,
    _otel_requested,
    _tracer,
)
