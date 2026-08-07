"""M5A identity/session API for local development and server adapters."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.domains.identity.session_service import ensure_user_device, issue_session, revoke_device, rotate_refresh_token

router = APIRouter()


class DeviceRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(default="default", min_length=1, max_length=128)
    email: str | None = None
    device_name: str = "local"


class IssueSessionRequest(BaseModel):
    user_id: str
    device_id: str
    scopes: list[str] = Field(default_factory=list, max_length=64)


class RotateRequest(BaseModel):
    refresh_token: str = Field(min_length=16, max_length=512)


@router.post("/devices")  # noqa: V103
def api_create_identity_device(req: DeviceRequest, db: Session = Depends(get_db)):  # noqa: V103
    user, device = ensure_user_device(db, subject=req.subject, tenant_id=req.tenant_id, email=req.email, device_name=req.device_name)
    return {"user_id": user.id, "device_id": device.id, "tenant_id": user.tenant_id, "device_key": device.device_key}


@router.post("/sessions")  # noqa: V103
def api_issue_identity_session(req: IssueSessionRequest, db: Session = Depends(get_db)):  # noqa: V103
    try:
        return issue_session(db, user_id=req.user_id, device_id=req.device_id, scopes=req.scopes)
    except ValueError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err


@router.post("/sessions/rotate")  # noqa: V103
def api_rotate_identity_session(req: RotateRequest, db: Session = Depends(get_db)):  # noqa: V103
    try:
        return rotate_refresh_token(db, req.refresh_token)
    except ValueError as err:
        raise HTTPException(status_code=401, detail=str(err)) from err


@router.post("/devices/{device_id}/revoke")  # noqa: V103
def api_revoke_identity_device(device_id: str, tenant_id: str = "default", db: Session = Depends(get_db)):  # noqa: V103
    try:
        count = revoke_device(db, device_id=device_id, tenant_id=tenant_id)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    return {"status": "revoked", "device_id": device_id, "sessions_revoked": count}
