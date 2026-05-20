"""Backwards-compatible re-export.

.. deprecated::
    The canonical home for logging configuration (JSON formatter,
    request- and job-id context binding, rotating file handler,
    mirroring) is now :mod:`app.platform.observability.logger`.
    Phase 5 step 5 of the module refactor moved the implementation
    out of ``app.utils`` because logging is cross-cutting
    observability infrastructure, not a generic utility.

    This file remains as a thin re-export shim. The 30+ modules that
    currently consume ``app.utils.logger`` continue to import via
    this shim path; bulk migration is deferred to Phase 7. New code
    MUST import from :mod:`app.platform.observability.logger`
    directly.
"""

from app.platform.observability.logger import *  # noqa: F401,F403 — re-export
from app.platform.observability.logger import (  # noqa: F401 — explicit (private context vars / state)
    _job_id,
    _logging_configured,
    _request_id,
)
