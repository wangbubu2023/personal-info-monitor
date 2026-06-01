"""Reconcile operation schema."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ReconcileOpType(StrEnum):
    ADD = "ADD"
    MERGE = "MERGE"
    SUPERSEDE = "SUPERSEDE"
    CONTRADICT = "CONTRADICT"
    IGNORE = "IGNORE"


class AtomReconcileOp(BaseModel):
    """One reconcile decision for a *new* atom against existing library atoms."""

    model_config = ConfigDict(extra="ignore")

    op: ReconcileOpType
    # The primary existing atom this op targets (supersede target / merge sink).
    atom_id: str | None = None
    candidate_atom_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


__all__ = ["AtomReconcileOp", "ReconcileOpType"]
