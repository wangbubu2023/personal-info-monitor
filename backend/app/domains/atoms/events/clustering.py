"""Rule-based event clustering.

Short-term heuristic (per plan §9.2): same domain + core-entity overlap +
time window. Embedding similarity is deferred. Only ``active``/``is_latest``
atoms participate so the cluster reflects the current state of the world.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.domains.atoms.id_gen import next_event_id
from app.domains.atoms.relation_infer.candidates import extract_entity_names
from app.domains.atoms.types import AtomRecord
from app.domains.atoms.vocab import AtomStatus
from app.models.atom import Atom
from app.models.atom_event import EventCluster, EventClusterAtom
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger

logger = get_logger(__name__)

TIME_WINDOW_DAYS = 30
_MAX_CLUSTERS_SCAN = 50


def _atom_seen_at(atom: AtomRecord, fallback) -> object:
    when = (atom.payload or {}).get("when") if atom.payload else None
    if isinstance(when, str) and len(when) >= 10:
        from app.domains.atoms.relation_infer.candidates import _parse_date

        parsed = _parse_date(when)
        if parsed is not None:
            return parsed
    return fallback


def assign_atom_to_cluster(session: Session, atom: AtomRecord) -> str | None:
    """Attach *atom* to a matching event cluster or create a new one.

    Returns the ``event_id``. Commits within the provided session.
    """
    entity_names = extract_entity_names(atom.atom_type.value, atom.payload)
    if not entity_names:
        return None

    seen_at = _atom_seen_at(atom, atom.created_at or utcnow_naive())
    window_start = seen_at - timedelta(days=TIME_WINDOW_DAYS)
    window_end = seen_at + timedelta(days=TIME_WINDOW_DAYS)

    clusters = (
        session.query(EventCluster)
        .filter(EventCluster.domain == atom.domain.value, EventCluster.status == "active")
        .order_by(EventCluster.last_seen_at.desc())
        .limit(_MAX_CLUSTERS_SCAN)
        .all()
    )

    matched_event_id: str | None = None
    for cluster in clusters:
        if cluster.last_seen_at is not None and not (
            window_start <= cluster.last_seen_at <= window_end
        ):
            continue
        member_ids = [
            r[0]
            for r in session.query(EventClusterAtom.atom_id)
            .filter(EventClusterAtom.event_id == cluster.event_id)
            .all()
        ]
        if not member_ids:
            continue
        member_atoms = session.query(Atom).filter(Atom.atom_id.in_(member_ids)).all()
        cluster_entities: set[str] = set()
        for member in member_atoms:
            cluster_entities |= extract_entity_names(member.atom_type, member.payload or {})
        if entity_names & cluster_entities:
            matched_event_id = cluster.event_id
            break

    if matched_event_id is None:
        matched_event_id = next_event_id(session)
        title = atom.canonical_text or atom.source_sentence
        session.add(
            EventCluster(
                event_id=matched_event_id,
                title=title[:500],
                domain=atom.domain.value,
                status="active",
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            )
        )
        session.flush()

    exists = (
        session.query(EventClusterAtom)
        .filter(
            EventClusterAtom.event_id == matched_event_id,
            EventClusterAtom.atom_id == atom.atom_id,
        )
        .first()
    )
    if exists is None:
        session.add(
            EventClusterAtom(event_id=matched_event_id, atom_id=atom.atom_id, role="update")
        )
    cluster = session.get(EventCluster, matched_event_id)
    if cluster is not None and seen_at is not None:
        if cluster.last_seen_at is None or seen_at > cluster.last_seen_at:
            cluster.last_seen_at = seen_at
        cluster.updated_at = utcnow_naive()
    session.commit()
    return matched_event_id


__all__ = ["TIME_WINDOW_DAYS", "assign_atom_to_cluster"]
