"""Optional structured layer: events / entities / relations.

Phase 6 of the refactor lights up the ``atoms`` domain:

* :mod:`app.domains.atoms.schema` — schema-versioned dataclasses + the
  ORM↔contract conversion helper. ``CURRENT_SCHEMA_VERSION`` and
  ``SUPPORTED_SCHEMA_VERSIONS`` live here.
* :mod:`app.domains.atoms.atomizer` — idempotent
  :func:`atomize_content`. Heuristic default extraction; gated by the
  ``ATOMS_ENABLED`` feature flag; swallows every exception so failures
  never block ingest.
* :mod:`app.domains.atoms.repository` — :class:`SqlAtomReader`, the
  concrete implementation of :class:`app.domains.contracts.atoms.AtomReader`
  that enrich consumes through the port.

Invariants (must hold regardless of operator config):

* ``ATOMS_ENABLED=false`` keeps the entire layer inert — no DB writes,
  no DB reads, no enrich path changes.
* ``atomize_content`` is idempotent (``ON CONFLICT (content_id) DO UPDATE``
  semantics over :class:`app.models.atom.ContentAtomBundle`) and never
  raises.
* Atoms are *not* part of the default ``fetch → ingest → enrich`` main
  path — the ingest finalizer only calls :func:`atomize_content` as a
  best-effort sidecar when the flag is on.
"""

from app.domains.atoms.atomizer import atomize_content
from app.domains.atoms.repository import SqlAtomReader, default_atom_reader
from app.domains.atoms.schema import (
    CURRENT_SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    atom_bundle_from_row,
)

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "SqlAtomReader",
    "atom_bundle_from_row",
    "atomize_content",
    "default_atom_reader",
]
