"""Platform-level authentication primitives.

This package exposes infrastructure-side helpers that any domain may call:

* ``cookies`` — lightweight cookie validity probing.

It contains **no business logic**. Domain-specific credential handling lives
under ``app.domains.fetch.auth``.
"""

from app.platform.auth.cookies import cookies_appear_valid, domain_match

__all__ = ["cookies_appear_valid", "domain_match"]
