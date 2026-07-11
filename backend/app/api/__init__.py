"""Compatibility shim — HTTP routers moved to :mod:`app.interfaces.http`.

Phase 5 step 15 of the modular refactor relocated the entire ``app.api``
package under ``app.interfaces.http``. To avoid touching every caller in
the same change, we keep ``app.api`` importable by aliasing the
canonical modules into :data:`sys.modules` under both names. Subsequent
calls (``from app.api.system import get_metrics_prometheus``,
``patch("app.api.contents_reader.get_settings")``, etc.) resolve to the
exact same module objects as the canonical ``app.interfaces.http.*``
paths — there is no duplicated state, and patches applied through either
name affect the other.

When Phase 7 sweeps the legacy entry points, this file and every
``app.api.<X>`` alias listed below should be deleted in a single change.
"""

from __future__ import annotations

import importlib
import sys

_CANONICAL_PACKAGE = "app.interfaces.http"

_MODULE_NAMES: tuple[str, ...] = (
    "",  # the package itself (app.api → app.interfaces.http)
    ".configs",
    ".configs_api_auth",
    ".configs_browser",
    # ``configs_common`` aggregator facade retired in Phase 7 — callers
    # must address the split modules below (``configs_common_auth`` /
    # ``configs_common_browser`` / ``configs_common_cookies``) directly.
    ".configs_common_auth",
    ".configs_common_browser",
    ".configs_common_cookies",
    ".configs_system",
    ".content_shared",
    ".contents",
    ".contents_cleanup",
    ".contents_crud",
    ".contents_reader",
    ".dashboard",
    ".digest",
    ".events",
    ".keywords",
    ".score_lab",
    ".sources",
    ".sources._helpers",
    ".sources.fetch_import",
    ".sources.mutation",
    ".sources.probe",
    ".sources.query",
    ".system",
)

for _suffix in _MODULE_NAMES:
    _canonical_name = _CANONICAL_PACKAGE + _suffix
    _alias_name = "app.api" + _suffix
    _module = importlib.import_module(_canonical_name)
    sys.modules[_alias_name] = _module

from app.interfaces.http import api_router  # noqa: E402

__all__ = ["api_router"]
