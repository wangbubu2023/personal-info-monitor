"""HTTP routes for the normalized news atom library."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.domains.atoms.atomizer import atomize_content_async
from app.domains.atoms.backfill import get_backfill_job, start_backfill
from app.domains.atoms.reconcile import get_reconcile_job, start_relations_reconcile
from app.domains.atoms.relations_repository import (
    RelationListFilters,
    default_atom_relations_repository,
)
from app.domains.atoms.repository import AtomListFilters, default_atom_repository
from app.domains.atoms.types import (
    AtomBackfillRequest,
    AtomBackfillResponse,
    AtomBackfillStatusResponse,
    AtomCreate,
    AtomListResponse,
    AtomRecord,
    AtomStatsResponse,
    AtomUpdate,
    AtomizeResponse,
    RelationCreate,
    RelationListResponse,
    RelationRecord,
    RelationReconcileRequest,
    RelationReconcileResponse,
    RelationReconcileStatusResponse,
    RelationUpdate,
)
from app.features import atoms_enabled, atoms_relations_enabled

router = APIRouter()
relations_router = APIRouter()


def _require_atoms_enabled() -> None:
    if not atoms_enabled():
        raise HTTPException(status_code=404, detail="Atoms layer is disabled (ATOMS_ENABLED=false)")


def _require_relations_enabled() -> None:
    _require_atoms_enabled()
    if not atoms_relations_enabled():
        raise HTTPException(
            status_code=404,
            detail="Atom relations are disabled (ATOMS_RELATIONS_ENABLED=false)",
        )


@router.get("", response_model=AtomListResponse)
def list_atoms(
    atom_type: str | None = Query(None, alias="type"),
    domain: str | None = None,
    verified: bool | None = None,
    atom_source: str | None = None,
    content_id: str | None = None,
    search: str | None = None,
    status: str | None = Query(
        "active",
        description="Lifecycle status filter; pass 'all' to include shadow/superseded.",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> AtomListResponse:
    _require_atoms_enabled()
    repo = default_atom_repository()
    status_filter = None if status in (None, "", "all") else status
    filters = AtomListFilters(
        atom_type=atom_type,
        domain=domain,
        verified=verified,
        atom_source=atom_source,
        content_id=content_id,
        search=search,
        status=status_filter,
    )
    items, total = repo.list_atoms(filters, page=page, page_size=page_size)
    return AtomListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/stats", response_model=AtomStatsResponse)
def atom_stats() -> AtomStatsResponse:
    _require_atoms_enabled()
    stats = default_atom_repository().stats()
    return AtomStatsResponse(**stats)


@router.post("/backfill", response_model=AtomBackfillResponse, status_code=202)
async def backfill_atoms(body: AtomBackfillRequest) -> AtomBackfillResponse:
    _require_atoms_enabled()
    try:
        job = await start_backfill(
            limit=body.limit,
            since=body.since,
            content_id=body.content_id,
            dry_run=body.dry_run,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AtomBackfillResponse(job_id=job.job_id, status=job.status)


@router.get("/backfill/{job_id}", response_model=AtomBackfillStatusResponse)
def backfill_status(job_id: str) -> AtomBackfillStatusResponse:
    _require_atoms_enabled()
    job = get_backfill_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Backfill job not found")
    data = job.to_dict()
    return AtomBackfillStatusResponse(**data)


@router.post("/content/{content_id}/atomize", response_model=AtomizeResponse)
async def atomize_one_content(content_id: str) -> AtomizeResponse:
    _require_atoms_enabled()
    ok = await atomize_content_async(content_id)
    return AtomizeResponse(content_id=content_id, ok=ok)


@router.get("/relations", response_model=RelationListResponse)
def list_relations(
    atom_id: str | None = Query(None),
    verified: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> RelationListResponse:
    _require_relations_enabled()
    repo = default_atom_relations_repository()
    filters = RelationListFilters(atom_id=atom_id, verified=verified)
    items, total = repo.list_relations(filters, page=page, page_size=page_size)
    return RelationListResponse(items=items, total=total, page=page, page_size=page_size)


@router.post("/relations/reconcile", response_model=RelationReconcileResponse, status_code=202)
async def reconcile_relations(body: RelationReconcileRequest) -> RelationReconcileResponse:
    _require_relations_enabled()
    try:
        job = await start_relations_reconcile(
            limit=body.limit,
            since=body.since,
            atom_id=body.atom_id,
            dry_run=body.dry_run,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RelationReconcileResponse(job_id=job.job_id, status=job.status)


@router.get("/relations/reconcile/{job_id}", response_model=RelationReconcileStatusResponse)
def reconcile_status(job_id: str) -> RelationReconcileStatusResponse:
    _require_relations_enabled()
    job = get_reconcile_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Reconcile job not found")
    data = job.to_dict()
    return RelationReconcileStatusResponse(**data)


@router.get("/{atom_id}", response_model=AtomRecord)
def get_atom(atom_id: str) -> AtomRecord:
    _require_atoms_enabled()
    record = default_atom_repository().get_atom(atom_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Atom not found")
    return record


@router.post("", response_model=AtomRecord, status_code=201)
def create_atom(body: AtomCreate) -> AtomRecord:
    _require_atoms_enabled()
    return default_atom_repository().create_atom(body)


@router.patch("/{atom_id}", response_model=AtomRecord)
def update_atom(atom_id: str, body: AtomUpdate) -> AtomRecord:
    _require_atoms_enabled()
    record = default_atom_repository().update_atom(atom_id, body)
    if record is None:
        raise HTTPException(status_code=404, detail="Atom not found")
    return record


@router.post("/{atom_id}/verify", response_model=AtomRecord)
def verify_atom(atom_id: str) -> AtomRecord:
    _require_atoms_enabled()
    record = default_atom_repository().update_atom(atom_id, AtomUpdate(verified=True))
    if record is None:
        raise HTTPException(status_code=404, detail="Atom not found")
    return record


@router.get("/{atom_id}/relations", response_model=RelationListResponse)
def list_atom_relations(atom_id: str) -> RelationListResponse:
    _require_relations_enabled()
    if default_atom_repository().get_atom(atom_id) is None:
        raise HTTPException(status_code=404, detail="Atom not found")
    items = default_atom_relations_repository().list_relations_for_atom(atom_id)
    return RelationListResponse(items=items, total=len(items), page=1, page_size=len(items) or 20)


@relations_router.post("", response_model=RelationRecord, status_code=201)
def create_relation(body: RelationCreate) -> RelationRecord:
    _require_relations_enabled()
    atom_repo = default_atom_repository()
    if atom_repo.get_atom(body.atom_a) is None or atom_repo.get_atom(body.atom_b) is None:
        raise HTTPException(status_code=404, detail="Atom not found")
    return default_atom_relations_repository().upsert_relation(body)


@relations_router.patch("/{rel_id}", response_model=RelationRecord)
def update_relation(rel_id: str, body: RelationUpdate) -> RelationRecord:
    _require_relations_enabled()
    record = default_atom_relations_repository().update_relation(rel_id, body)
    if record is None:
        raise HTTPException(status_code=404, detail="Relation not found")
    return record


@relations_router.delete("/{rel_id}", status_code=204)
def delete_relation(rel_id: str) -> None:
    _require_relations_enabled()
    if not default_atom_relations_repository().delete_relation(rel_id):
        raise HTTPException(status_code=404, detail="Relation not found")


@relations_router.post("/{rel_id}/verify", response_model=RelationRecord)
def verify_relation(rel_id: str) -> RelationRecord:
    _require_relations_enabled()
    record = default_atom_relations_repository().apply_verified_corroboration(rel_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Relation not found")
    return record
