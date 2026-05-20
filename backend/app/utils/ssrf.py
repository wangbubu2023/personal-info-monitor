"""Backwards-compatible re-export.

.. deprecated::
    The canonical home for the outbound SSRF guard is now
    :mod:`app.platform.security.ssrf`. Phase 5 step 3 of the module
    refactor moved the implementation out of ``app.utils`` because
    outbound-host validation is cross-cutting security
    infrastructure, not a generic utility.

    This file remains as a thin re-export shim so existing imports
    keep working. Phase 7 removes it. New code MUST import from
    :mod:`app.platform.security.ssrf` directly.

    Note: ``from ... import *`` does NOT carry underscore-prefixed
    names. ``app.services.probe_service`` (and probe tests via
    ``patch("app.utils.ssrf._resolve_host_addresses")``) reach for
    the internal helpers ``_is_private_address`` and
    ``_resolve_host_addresses``, so they are re-exported explicitly
    below.
"""

from app.platform.security.ssrf import (  # noqa: F401 — re-export
    _is_private_address,
    _resolve_host_addresses,
    assert_public_http_target,
    check_before_fetch,
    hosts_match,
)

__all__ = [
    "assert_public_http_target",
    "check_before_fetch",
    "hosts_match",
]
