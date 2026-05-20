"""Platform-level authentication primitives.

This package exposes infrastructure-side helpers that any domain may call:

* ``cookies`` — lightweight cookie validity probing.
* ``api_credentials`` — FastAPI-friendly decryption of stored API
  credentials (relocated from ``app.services.api_config_credentials`` in
  Phase 4.6).
* ``api_key`` — ``verify_api_key`` FastAPI dependency that validates the
  ``X-API-Key`` request header against ``settings.pim_api_key``
  (relocated from ``app.auth`` in Phase 5 step 8). The old ``app.auth``
  path remains as a thin re-export shim because four call sites still
  import from it (``app.api.__init__``, ``app.main``,
  ``tests/conftest.py``, ``tests/test_configs_browser.py``) plus six
  ``patch("app.auth.get_settings")`` sites in ``test_auth_unit.py``.

It contains **no business logic**. Domain-specific credential handling lives
under ``app.domains.fetch.auth``.
"""

from app.platform.auth.api_key import verify_api_key
from app.platform.auth.cookies import cookies_appear_valid, domain_match

__all__ = ["cookies_appear_valid", "domain_match", "verify_api_key"]
