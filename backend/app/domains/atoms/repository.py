"""SQLAlchemy-backed :class:`AtomReader` implementation.

This is the concrete port that :mod:`app.domains.enrich` consumes through
the abstract :class:`app.domains.contracts.atoms.AtomReader` Protocol.
The class deliberately exposes nothing besides ``get_bundle`` — enrich
must not reach for SQLAlchemy sessions or the ORM model directly so the
atoms feature can be swapped/stubbed (e.g. with an in-memory reader in
tests) without changing enrich.

When ``ATOMS_ENABLED=false`` :func:`SqlAtomReader.get_bundle` short-
circuits to ``None`` so callers that already hold a reader instance
don't accidentally touch the database.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.atoms.schema import atom_bundle_from_row
from app.domains.contracts.atoms import AtomBundle
from app.features import atoms_enabled
from app.models import ContentAtomBundle
from app.utils.logger import get_logger

logger = get_logger(__name__)


class SqlAtomReader:
    """Concrete :class:`AtomReader` backed by SQLAlchemy."""

    def __init__(self, session_factory):
        """``session_factory`` is a zero-arg callable returning a :class:`Session`."""
        self._session_factory = session_factory

    def get_bundle(self, content_id: str) -> AtomBundle | None:
        if not atoms_enabled():
            return None

        session: Session = self._session_factory()
        try:
            row = (
                session.query(ContentAtomBundle)
                .filter(ContentAtomBundle.content_id == content_id)
                .first()
            )
            return atom_bundle_from_row(row)
        except Exception as exc:  # noqa: BLE001 - read path must never propagate
            logger.warning("SqlAtomReader.get_bundle failed for %s: %s", content_id, exc)
            return None
        finally:
            session.close()


def default_atom_reader() -> SqlAtomReader:
    """Return a :class:`SqlAtomReader` bound to the process SQLAlchemy factory."""
    from app.database import SessionLocal

    return SqlAtomReader(SessionLocal)


__all__ = ["SqlAtomReader", "default_atom_reader"]
