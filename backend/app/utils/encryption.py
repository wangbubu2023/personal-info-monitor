"""Backwards-compatible re-export.

.. deprecated::
    The canonical home for Fernet-based credential encryption is now
    :mod:`app.platform.security.encryption`. Phase 5 step 3 of the
    module refactor moved the implementation out of ``app.utils``
    because credential sealing is cross-cutting security
    infrastructure, not a generic utility.

    This file remains as a thin re-export shim so existing imports
    keep working. Phase 7 removes it. New code MUST import from
    :mod:`app.platform.security.encryption` directly.

    Note: ``from ... import *`` does NOT carry underscore-prefixed
    names. ``test_encryption_coverage.py`` reaches for the envelope
    constants directly (``_LEGACY_STATIC_SALT`` / ``_SALT_LENGTH`` /
    ``_V2_PREFIX``) and the internal helpers (``_derive_fernet``,
    ``_encrypt_bytes``, ``_decrypt_bytes``), so they are re-exported
    explicitly below.
"""

from app.platform.security.encryption import (  # noqa: F401 — re-export
    _ITERATIONS_DEFAULT,
    _ITERATIONS_LEGACY,
    _ITERATIONS_V2,
    _ITERATIONS_V3,
    _LEGACY_STATIC_SALT,
    _SALT_LENGTH,
    _V2_PREFIX,
    _V3_PREFIX,
    _V4_PREFIX,
    _decrypt_bytes,
    _derive_fernet,
    _derive_fernet_v4,
    _encrypt_bytes,
    decrypt_data,
    decrypt_string,
    encrypt_data,
    encrypt_string,
)

__all__ = [
    "decrypt_data",
    "decrypt_string",
    "encrypt_data",
    "encrypt_string",
]
