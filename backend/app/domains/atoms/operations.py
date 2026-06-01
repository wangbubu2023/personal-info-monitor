"""Operation log for atom decisions (extract / filter / reconcile / manual).

Provides an auditable trail so it is possible to explain why an atom was
created, shadowed, superseded, merged, or flagged — mirroring HY-memory's
pipeline log.
"""

from __future__ import annotations

from typing import Any

from app.domains.atoms.id_gen import next_operation_id
from app.domains.atoms.vocab import AtomOperationType
from app.models.atom import AtomOperation
from app.utils.logger import get_logger

logger = get_logger(__name__)


class SqlAtomOperationRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def record(
        self,
        *,
        operation_type: AtomOperationType | str,
        content_id: str | None = None,
        atom_id: str | None = None,
        related_atom_ids: list[str] | None = None,
        model_provider: str | None = None,
        model_name: str | None = None,
        prompt: str | None = None,
        raw_response: str | None = None,
        parsed: Any = None,
        reason: str | None = None,
        quality_flags: list[str] | None = None,
    ) -> str | None:
        """Persist one operation row. Never raises (audit logging must not break flows)."""
        op_value = (
            operation_type.value
            if isinstance(operation_type, AtomOperationType)
            else str(operation_type)
        )
        session = self._session_factory()
        try:
            row = AtomOperation(
                operation_id=next_operation_id(session),
                operation_type=op_value,
                content_id=content_id,
                atom_id=atom_id,
                related_atom_ids=list(related_atom_ids or []),
                model_provider=model_provider,
                model_name=model_name,
                prompt=prompt,
                raw_response=raw_response,
                parsed=parsed,
                reason=reason,
                quality_flags=list(quality_flags or []),
            )
            session.add(row)
            session.commit()
            return row.operation_id
        except Exception as exc:  # noqa: BLE001
            logger.warning("record atom operation failed (%s): %s", op_value, exc)
            try:
                session.rollback()
            except Exception:  # noqa: BLE001
                pass
            return None
        finally:
            session.close()


def default_atom_operation_repository() -> SqlAtomOperationRepository:
    from app.database import SessionLocal

    return SqlAtomOperationRepository(SessionLocal)


__all__ = ["SqlAtomOperationRepository", "default_atom_operation_repository"]
