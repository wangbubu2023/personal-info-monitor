"""Optional structured layer: events / entities / relations.

Phase 6 of the refactor adds:

* ``domains/atoms/schema.py`` — schema-versioned dataclasses
* ``domains/atoms/atomizer.py`` — idempotent ``atomize_content(content_id)``
* ``domains/atoms/repository.py`` — implements
  :class:`app.domains.contracts.atoms.AtomReader` against SQLite

The whole package stays inert when ``ATOMS_ENABLED=false``. Atomisation
failures MUST NOT block ingest; atoms are not part of the default
``fetch → ingest → enrich`` main path.
"""
