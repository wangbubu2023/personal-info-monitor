"""Paid-source, Local Capture, canary, and archive-audit HTTP handlers."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.domains.fetch.auth_zip import MAX_COMPRESSED_ARCHIVE_BYTES, extract_auth_archive_safely
from app.domains.fetch.local_capture import (
    MAX_READER_DOC_BODY_CHARS,
    MAX_READER_DOC_TITLE_CHARS,
    issue_local_capture_task_token,
    process_local_capture,
)
from app.domains.fetch.paid_matrix import (
    ack_session_recovery,
    complete_session_recovery,
    record_paid_source_result,
    run_daily_canary_for_source,
    trigger_session_expiration,
)
from app.domains.fetch.daily_canary import source_health_history

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


class LocalCaptureTokenRequest(BaseModel):
    device_id: str
    origin_url: str


class LocalCaptureRequest(BaseModel):
    device_id: str
    task_token: str
    origin_url: str
    reader_doc_title: str = Field(min_length=1, max_length=MAX_READER_DOC_TITLE_CHARS)
    reader_doc_body: str = Field(min_length=1, max_length=MAX_READER_DOC_BODY_CHARS)


class DailyCanaryRequest(BaseModel):
    source_id: str
    sample_body: str | None = None
    run_date_str: str | None = None


@router.post("/record")  # noqa: V103
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
        "status": "success" if audit.failure_code is None else "failed",
        "audit_id": audit.id,
        "last_readable_success_at": audit.last_readable_success_at.isoformat() if audit.last_readable_success_at else None,
        "success_rate_7d": audit.success_rate_7d,
        "failure_code": audit.failure_code,
        "recovery_action": audit.recovery_action,
    }


@router.post("/trigger-recovery-drill")  # noqa: V103
def api_trigger_recovery(req: SessionTriggerRequest, db: Session = Depends(get_db)):
    audit = trigger_session_expiration(db, auth_config_id=req.auth_config_id, root_cause=req.root_cause)
    return {"status": "triggered", "audit_id": audit.id, "detected_at": audit.detected_at.isoformat()}


@router.post("/ack-recovery/{audit_id}")  # noqa: V103
def api_ack_recovery(audit_id: str, db: Session = Depends(get_db)):
    audit = ack_session_recovery(db, audit_id=audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit session not found")
    return {"status": "acked", "acked_at": audit.acked_at.isoformat() if audit.acked_at else None}


@router.post("/complete-recovery/{audit_id}")  # noqa: V103
def api_complete_recovery(audit_id: str, db: Session = Depends(get_db)):
    audit = complete_session_recovery(db, audit_id=audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit session not found")
    return {
        "status": "recovered",
        "recovered_at": audit.recovered_at.isoformat() if audit.recovered_at else None,
        "mttr_seconds": audit.mttr_seconds,
    }


@router.post("/local-capture/task-token")  # noqa: V103
def api_issue_local_capture_token(req: LocalCaptureTokenRequest, db: Session = Depends(get_db)):
    try:
        token = issue_local_capture_task_token(db, req.device_id, req.origin_url)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    return {"task_token": token, "expires_in_seconds": 300}


@router.post("/local-capture")  # noqa: V103
def api_local_capture(req: LocalCaptureRequest, db: Session = Depends(get_db)):
    try:
        audit = process_local_capture(
            db,
            device_id=req.device_id,
            task_token=req.task_token,
            origin_url=req.origin_url,
            reader_doc_title=req.reader_doc_title,
            reader_doc_body=req.reader_doc_body,
        )
        return {
            "status": audit.ingest_status,
            "audit_id": audit.id,
            "content_id": audit.content_id,
            "checksum": audit.reader_doc_checksum,
        }
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err


@router.post("/daily-canary")  # noqa: V103
def api_daily_canary(req: DailyCanaryRequest, db: Session = Depends(get_db)):  # noqa: V103
    try:
        canary = run_daily_canary_for_source(
            db,
            source_id=req.source_id,
            sample_body=req.sample_body,
            run_date_str=req.run_date_str,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    return {
        "status": canary.status,
        "canary_id": canary.id,
        "paywall_residual_detected": canary.paywall_residual_detected,
    }


@router.get("/health/{source_id}")  # noqa: V103
def api_source_health(source_id: str, days: int = 7, db: Session = Depends(get_db)):  # noqa: V103
    return {"source_id": source_id, "days": max(1, min(days, 90)), "items": source_health_history(db, source_id, days=days)}


async def _validate_upload_size(file: UploadFile, max_bytes: int) -> int:
    await file.seek(0)
    total = 0
    while True:
        chunk = await file.read(min(1024 * 1024, max_bytes - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail=f"Uploaded archive exceeds {max_bytes} bytes")
    await file.seek(0)
    return total


@router.post("/extract-archive")  # noqa: V103
async def api_extract_archive(file: UploadFile = File(...), db: Session = Depends(get_db)):
    await _validate_upload_size(file, MAX_COMPRESSED_ARCHIVE_BYTES)
    extraction = extract_auth_archive_safely(
        db,
        archive_name=file.filename or "archive.zip",
        zip_bytes=file.file,
    )
    return {
        "status": extraction.status,
        "extraction_id": extraction.id,
        "entry_count": extraction.entry_count,
        "uncompressed_bytes": extraction.uncompressed_bytes,
        "compression_ratio": extraction.compression_ratio,
        "rejection_reason": extraction.rejection_reason,
    }
