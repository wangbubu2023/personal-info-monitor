"""Business services package.

Phase 7 retired the legacy re-export bundle that pre-loaded service
classes into this namespace. New code should import canonical domain
modules directly, for example :mod:`app.domains.enrich.digest` and
:mod:`app.domains.system.doctor`. Thin ``app.services.*`` modules remain
only where older callers still need compatibility.
"""
