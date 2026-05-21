"""Optional structured layer: normalized news atoms (Schema v2)."""

from app.domains.atoms.atomizer import atomize_content, atomize_content_async
from app.domains.atoms.relations_repository import (
    SqlAtomRelationRepository,
    default_atom_relations_repository,
)
from app.domains.atoms.repository import (
    SqlAtomReader,
    SqlAtomRepository,
    default_atom_reader,
    default_atom_repository,
)
from app.domains.atoms.schema import CURRENT_SCHEMA_VERSION, SUPPORTED_SCHEMA_VERSIONS

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "SqlAtomReader",
    "SqlAtomRelationRepository",
    "SqlAtomRepository",
    "atomize_content",
    "atomize_content_async",
    "default_atom_reader",
    "default_atom_relations_repository",
    "default_atom_repository",
]
