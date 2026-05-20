"""Utility functions package.

``encrypt_data`` / ``decrypt_data`` re-exported here are sourced from
:mod:`app.platform.security.encryption` (Phase 5 step 3 relocation);
``app.utils.encryption`` itself is a re-export shim.

``get_logger`` re-exported here is sourced from
:mod:`app.platform.observability.logger` (Phase 5 step 5 relocation);
``app.utils.logger`` itself is a re-export shim.
"""

from app.platform.observability.logger import get_logger
from app.platform.security.encryption import decrypt_data, encrypt_data

__all__ = ["encrypt_data", "decrypt_data", "get_logger"]
