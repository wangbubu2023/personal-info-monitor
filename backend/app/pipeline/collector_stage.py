"""Compatibility alias for the canonical fetch-domain collector stage."""

from __future__ import annotations

import sys

from app.domains.fetch import collector_stage as _collector_stage

sys.modules[__name__] = _collector_stage
