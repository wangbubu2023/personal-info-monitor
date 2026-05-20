"""Business services package.

Phase 7 retired the legacy re-export bundle that pre-loaded
``DigestService`` / ``MonitorService`` into this namespace. Importers
must address the canonical submodule directly
(``app.services.digest_service`` / ``app.services.monitor_service``).
The blueprint plans further redistribution into
:mod:`app.domains.enrich` and :mod:`app.domains.sources`.
"""
