"""Rule-based entity mention extraction from structured atom payloads.

LLM is reserved (per plan) for alias merging and ambiguous disambiguation; the
common case is read straight from the payload's ``who`` / ``entities`` /
``source_org`` fields.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domains.atoms.types import AtomRecord
from app.domains.atoms.vocab import AtomType, SubjectType

_DEFAULT_TYPE = SubjectType.ORGANIZATION.value


@dataclass(frozen=True)
class EntityMention:
    name: str
    entity_type: str
    role: str


def _clean(name: str) -> str:
    return " ".join((name or "").split()).strip()


def extract_entity_mentions(atom: AtomRecord) -> list[EntityMention]:
    """Return deduplicated entity mentions for an atom from its payload."""
    payload = atom.payload or {}
    seen: set[tuple[str, str]] = set()
    out: list[EntityMention] = []

    def _add(name: str, entity_type: str, role: str) -> None:
        clean = _clean(name)
        if len(clean) < 2:
            return
        key = (clean, role)
        if key in seen:
            return
        seen.add(key)
        out.append(EntityMention(name=clean, entity_type=entity_type or _DEFAULT_TYPE, role=role))

    if atom.atom_type in (AtomType.INFO, AtomType.OPINION):
        for who in payload.get("who") or []:
            if isinstance(who, dict) and who.get("name"):
                _add(str(who["name"]), str(who.get("type") or _DEFAULT_TYPE), "subject")
    if atom.atom_type == AtomType.INFO:
        for entity in payload.get("entities") or []:
            if entity:
                _add(str(entity), _DEFAULT_TYPE, "mentioned")
    if atom.atom_type == AtomType.DATA:
        org = payload.get("source_org")
        if org:
            _add(str(org), SubjectType.ORGANIZATION.value, "source_org")

    return out


__all__ = ["EntityMention", "extract_entity_mentions"]
