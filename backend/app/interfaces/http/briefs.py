"""Briefs HTTP handlers."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.domains.enrich.brief_service import create_brief_snapshot, override_brief_modality_violation

router = APIRouter()


class CreateBriefRequest(BaseModel):
    period_key: str
    brief_type: str
    title: str
    summary_content: str
    upstream_event_snapshot_ids: list[str]
    upstream_modality: str = "reported"
    brief_modality: str = "reported"
    generator_version: str = "v1.0"


class OverrideModalityRequest(BaseModel):
    override_by: str
    override_reason: str


@router.post("")
def api_create_brief(req: CreateBriefRequest, db: Session = Depends(get_db)):
    try:
        brief, audit = create_brief_snapshot(
            db,
            period_key=req.period_key,
            brief_type=req.brief_type,
            title=req.title,
            summary_content=req.summary_content,
            upstream_event_snapshot_ids=req.upstream_event_snapshot_ids,
            upstream_modality=req.upstream_modality,
            brief_modality=req.brief_modality,
            generator_version=req.generator_version,
        )
        return {
            "status": "created",
            "brief_id": brief.id,
            "period_key": brief.period_key,
            "modality_status": brief.modality_status,
            "violation_detected": (audit is not None),
        }
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err


@router.post("/{brief_id}/override")
def api_override_modality(brief_id: str, req: OverrideModalityRequest, db: Session = Depends(get_db)):
    try:
        brief = override_brief_modality_violation(
            db,
            brief_id=brief_id,
            override_by=req.override_by,
            override_reason=req.override_reason,
        )
        return {"status": "override_approved", "brief_id": brief.id, "modality_status": brief.modality_status}
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
