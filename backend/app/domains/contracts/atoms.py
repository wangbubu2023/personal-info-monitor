"""Cross-domain contracts owned by the ``atoms`` domain.

Atoms are the optional structured layer (events / entities / relations) that
the enrich domain reads through the :class:`AtomReader` protocol. The
default flow does **not** depend on atoms; ``ATOMS_ENABLED=false`` keeps
the entire layer inert.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class AtomBundle:
    """A schema-versioned bundle of structured atoms for one content row.

    ``schema_version`` is bumped whenever the on-disk shape of ``events``,
    ``entities`` or ``relations`` changes — readers MUST refuse to consume
    bundles with an unknown version.
    """

    content_id: str
    schema_version: int
    events: tuple[Mapping[str, Any], ...] = ()
    entities: tuple[Mapping[str, Any], ...] = ()
    relations: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


class AtomReader(Protocol):
    """Read-only port that ``enrich`` uses to consume atoms.

    Concrete implementations live in ``app.domains.atoms``; the enrich
    domain MUST depend only on this protocol so it can run with the
    atoms layer disabled or replaced by a stub.
    """

    def get_bundle(self, content_id: str) -> AtomBundle | None:
        """Return the latest bundle for ``content_id`` or ``None`` if absent."""
        ...
