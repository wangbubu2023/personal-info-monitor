"""Schema-versioned in-memory representation of an atom bundle.

The on-disk shape is defined by ``app.models.atom.ContentAtomBundle``;
the cross-domain port (``app.domains.contracts.atoms.AtomBundle``) is
the immutable read-only view that enrich consumes. This module owns the
*version constant* and the conversion helpers between ORM ⇄ contract.

When the JSON payload shape ever changes (a new event/entity/relation
field, a rename, a tuple⇄dict swap, …) bump ``CURRENT_SCHEMA_VERSION``
in this module, add the deserializer for the new version, and make
:func:`atom_bundle_from_row` refuse the unknown legacy bumps. Readers
that consume ``AtomBundle`` MUST inspect ``schema_version`` before
trusting payload semantics.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from app.domains.contracts.atoms import AtomBundle

CURRENT_SCHEMA_VERSION: int = 1

#: Versions this build knows how to read. Refusing unknown versions is
#: the cheap forward-compat guard the blueprint requires.
SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1})


def _coerce_tuple_of_mappings(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not value:
        return ()
    if isinstance(value, Mapping):
        # Stored as a single dict — wrap defensively. Shouldn't happen for
        # events/entities/relations but JSON-roundtrips can lose list-ness.
        return (dict(value),)
    if isinstance(value, Iterable):
        return tuple(dict(item) for item in value if isinstance(item, Mapping))
    return ()


def _coerce_metadata(value: Any) -> Mapping[str, Any]:
    if not value or not isinstance(value, Mapping):
        return {}
    return dict(value)


def atom_bundle_from_row(row: Any) -> AtomBundle | None:
    """Convert a ``ContentAtomBundle`` ORM row into the contract DTO.

    Returns ``None`` if the row reports an unsupported schema version so
    callers can keep the atoms layer inert when reading older or newer
    rows.
    """
    if row is None:
        return None

    schema_version = int(getattr(row, "schema_version", 0) or 0)
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        return None

    return AtomBundle(
        content_id=str(row.content_id),
        schema_version=schema_version,
        events=_coerce_tuple_of_mappings(row.events),
        entities=_coerce_tuple_of_mappings(row.entities),
        relations=_coerce_tuple_of_mappings(row.relations),
        metadata=_coerce_metadata(getattr(row, "bundle_metadata", None)),
    )


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "atom_bundle_from_row",
]
