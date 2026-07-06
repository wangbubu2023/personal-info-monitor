"""Compatibility alias for the canonical fetch coordinator."""

from __future__ import annotations

import sys

from app.domains.fetch import coordinator as _coordinator

sys.modules[__name__] = _coordinator
