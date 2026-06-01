"""L5 knowledge-entity layer (SQL, no graph database)."""

from app.domains.atoms.entities.extract import EntityMention, extract_entity_mentions
from app.domains.atoms.entities.repository import (
    SqlEntityRepository,
    default_entity_repository,
)

__all__ = [
    "EntityMention",
    "SqlEntityRepository",
    "default_entity_repository",
    "extract_entity_mentions",
]
