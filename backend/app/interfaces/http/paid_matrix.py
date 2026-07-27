"""Paid-source matrix, Local capture, and Archive extraction HTTP handlers."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.domains.fetch.auth_zip import extract_auth_archive_safely
from app.domains.fetch.local_capture import process_local_capture
from app.domains.fetch.paid_matrix import (
    ack_session_recovery,
    complete_session_recovery,
    record_paid_source_result,
    run_daily_canary_for_source,
    trigger_session_expiration,
)

router = APIRouter()


class PaidSourceRecordRequest(BaseModel):
    source_id: str
    body_text: str | None = None
    discovery_url: str | None = None
    validation_url: str | None = None
    http_status: int = 200


class SessionTriggerRequest(BaseModel):
    auth_config_id: str
    root_cause: str = "MANUAL_TEST_EXPIRATION"


class LocalCaptureRequest(BaseModel):
    device_id: str
    task_token: str
    origin_url: str
    reader_doc_title: str
    reader_doc_body: str
    allowlist: list[str] | None = None


class DailyCanaryRequest(BaseModel):
    source_id: str
    sample_body: str | None = None
    run_date_str: str | None = None


@router.post("/record")
def api_record_paid_source(req: PaidSourceRecordRequest, db: Session = Depends(get_db)):
    audit = record_paid_source_result(
        db,
        source_id=req.source_id,
        body_text=req.body_text,
        discovery_url=req.discovery_url,
        validation_url=req.validation_url,
        http_status=req.http_status,
    )
    return {
        "status": "success",
        "audit_id": audit.id,
        "last_readable_success_at": audit.last_readable_success_at.isoformat() if audit.last_readable_success_at else None,
        "failure_code": audit.failure_code,
        "recovery_action": audit.recovery_action,
    }


@router.post("/trigger-recovery-drill")
def api_trigger_recovery(req: SessionTriggerRequest, db: Session = Depends(get_db)):
    audit = trigger_session_expiration(db, auth_config_id=req.auth_config_id, root_cause=req.root_cause)
    return {"status": "triggered", "audit_id": audit.id, "detected_at": audit.detected_at.isoformat()}


@router.post("/ack-recovery/{audit_id}")
def api_ack_recovery(audit_id: str, db: Session = Depends(get_db)):
    audit = ack_session_recovery(db, audit_id=audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit session not found")
    return {"status": "acked", "acked_at": audit.acked_at.isoformat() if audit.acked_at else None}


@router.post("/complete-recovery/{audit_id}")
def api_complete_recovery(audit_id: str, db: Session = Depends(get_db)):
    audit = complete_session_recovery(db, audit_id=audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit session not found")
    return {
        "status": "recovered",
        "recovered_at": audit.recovered_at.isoformat() if audit.recovered_at else None,
        "mttr_seconds": audit.mttr_seconds,
    }


@router.post("/local-capture")
def api_local_capture(req: LocalCaptureRequest, db: Session = Depends(get_db)):
    try:
        audit = process_local_capture(
            db,
            device_id=req.device_id,
            task_token=req.task_token,
            origin_url=req.origin_url,
            reader_doc_title=req.reader_doc_title,
            reader_doc_body=req.reader_doc_body,
            allowlist=req.allowlist,
        )
        return {"status": "captured", "audit_id": audit.id, "checksum": audit.reader_doc_checksum}
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err


@router.post("/daily-canary")
def api_daily_canary(req: DailyCanaryRequest, db: Session = Depends(get_db)):
    canary = run_daily_canary_for_source(
        db,
        source_id=req.source_id,
        sample_body=req.sample_body,
        run_date_str=req.run_date_str,
    )
    return {
        "status": canary.status,
        "canary_id": canary.id,
        "paywall_residual_detected": canary.paywall_residual_detected,
    }


@router.post("/extract-archive")
async def api_extract_archive(file: UploadFile = File(...), db: Session = Depends(get_db)):
    bytes_content = await file.read()
    extraction = extract_auth_archive_safely(db, archive_name=file.filename or "archive.zip", zip_bytes=bytes_content)
    return {
        "status": extraction.status,
        "extraction_id": extraction.id,
        "entry_count": extraction.entry_count,
        "uncompressed_bytes": extraction.uncompressed_bytes,
        "compression_ratio": extraction.compression_ratio,
        "rejection_reason": extraction.rejection_reason,
    }
