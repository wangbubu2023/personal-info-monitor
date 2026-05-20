"""Utility functions package.

``encrypt_data`` / ``decrypt_data`` re-exported here are sourced from
:mod:`app.platform.security.encryption` (Phase 5 step 3 relocation);
``app.utils.encryption`` itself is a re-export shim.
"""

from app.platform.security.encryption import decrypt_data, encrypt_data
from app.utils.logger import get_logger

__all__ = ["encrypt_data", "decrypt_data", "get_logger"]
