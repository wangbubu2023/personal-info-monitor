"""Cross-domain contracts owned by the ``atoms`` domain."""

from __future__ import annotations

from typing import Any, Protocol


class AtomReader(Protocol):
    """Read-only port that ``enrich`` uses to consume atoms."""

    def get_atoms_for_content(self, content_id: str) -> tuple[Any, ...]:
        """Return normalized atoms extracted from one content row."""
        ...
