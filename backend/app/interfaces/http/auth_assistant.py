"""HTTP API for local PIM Auth Assistant pairing and imports."""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_async_db
from app.domains.fetch.auth.bundle_import import import_auth_bundle
from app.interfaces.http.configs_common_auth import serialize_auth_config
from app.models.auth_assistant import (
    AuthAssistantDevice,
    AuthAssistantDeviceStatus,
    AuthAssistantImportLog,
    AuthAssistantPairingToken,
    AuthAssistantTokenStatus,
)
from app.models.auth_config import AuthConfig
from app.platform.auth import verify_api_key
from app.platform.auth.assistant import (
    expires_at_from_now,
    generate_device_token,
    generate_pairing_token,
    hash_secret,
    require_auth_assistant_device,
    token_hint,
)
from app.platform.auth.bundle import AuthBundleError
from app.platform.runtime.update_check import current_version
from app.utils.datetime import utcnow_naive

router = APIRouter()
_device_token_header = APIKeyHeader(name="X-Auth-Assistant-Token", auto_error=False)

_PAIRING_TOKEN_TTL_MINUTES = 10
_AUTH_EXPORT_KIND = "pim.auth_export"
_AUTH_BUNDLE_KIND = "pim.auth_bundle"


class PairingTokenCreateRequest(BaseModel):
    ttl_minutes: int = Field(default=_PAIRING_TOKEN_TTL_MINUTES, ge=1, le=60)


class PairingTokenResponse(BaseModel):
    pairing_token: str
    pairing_url: str
    expires_at: str
    token_hint: str


class PairingClaimRequest(BaseModel):
    pairing_token: str
    device_name: str = Field(default="PIM Auth Assistant", min_length=1, max_length=255)
    app_version: str | None = Field(default=None, max_length=64)


class PairingClaimResponse(BaseModel):
    device_token: str
    device: dict[str, Any]
    server: dict[str, Any]
    capabilities: dict[str, bool]


class AuthAssistantBundleImportRequest(BaseModel):
    bundle: dict[str, Any]
    name: str | None = None
    bind_matching_sources: bool = True
    create_browser_session: bool = True


@router.post("/pairing-tokens", response_model=PairingTokenResponse, dependencies=[Depends(verify_api_key)])
async def create_pairing_token(
    request_body: PairingTokenCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """Create a one-time pairing token from authenticated PIM Web."""

    raw_token = generate_pairing_token()
    token = AuthAssistantPairingToken(
        token_hash=hash_secret(raw_token),
        token_hint=token_hint(raw_token),
        expires_at=expires_at_from_now(request_body.ttl_minutes),
        status=AuthAssistantTokenStatus.PENDING,
    )
    db.add(token)
    await db.commit()
    server_url = str(request.base_url).rstrip("/")
    pairing_url = f"pim-auth://pair?server={quote(server_url, safe='')}&token={quote(raw_token, safe='')}"
    return PairingTokenResponse(
        pairing_token=raw_token,
        pairing_url=pairing_url,
        expires_at=token.expires_at.isoformat() + "Z",
        token_hint=token.token_hint,
    )


@router.post("/pair", response_model=PairingClaimResponse)
async def claim_pairing_token(
    request_body: PairingClaimRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """Exchange a short one-time pairing token for a device token."""

    raw_token = request_body.pairing_token.strip()
    result = await db.execute(
        select(AuthAssistantPairingToken).where(
            AuthAssistantPairingToken.token_hash == hash_secret(raw_token)
        )
    )
    pairing = result.scalar_one_or_none()
    if pairing is None:
        raise HTTPException(status_code=404, detail="Pairing token not found")
    if pairing.status != AuthAssistantTokenStatus.PENDING:
        raise HTTPException(status_code=409, detail="Pairing token has already been used or revoked")
    if pairing.expires_at <= utcnow_naive():
        pairing.status = AuthAssistantTokenStatus.EXPIRED
        await db.commit()
        raise HTTPException(status_code=410, detail="Pairing token has expired")

    raw_device_token = generate_device_token()
    capabilities = _auth_assistant_capabilities()
    device = AuthAssistantDevice(
        name=request_body.device_name.strip() or "PIM Auth Assistant",
        token_hash=hash_secret(raw_device_token),
        status=AuthAssistantDeviceStatus.ACTIVE,
        app_version=request_body.app_version,
        last_seen_at=utcnow_naive(),
        capabilities=capabilities,
        metadata_={"paired_from": str(request.client.host) if request.client else None},
    )
    db.add(device)
    await db.flush()
    pairing.status = AuthAssistantTokenStatus.CLAIMED
    pairing.claimed_at = utcnow_naive()
    pairing.device_id = device.id
    await db.commit()
    await db.refresh(device)

    server_url = str(request.base_url).rstrip("/")
    return PairingClaimResponse(
        device_token=raw_device_token,
        device=_serialize_device(device),
        server={"name": "PIM", "base_url": server_url, "version": current_version()},
        capabilities=capabilities,
    )


@router.get("/devices", dependencies=[Depends(verify_api_key)])
async def list_devices(db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(AuthAssistantDevice).order_by(AuthAssistantDevice.created_at.desc()))
    return [_serialize_device(device) for device in result.scalars().all()]


@router.delete("/devices/{device_id}", dependencies=[Depends(verify_api_key)])
async def revoke_device(device_id: str, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(AuthAssistantDevice).where(AuthAssistantDevice.id == device_id))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Auth Assistant device not found")
    device.status = AuthAssistantDeviceStatus.REVOKED
    device.revoked_at = utcnow_naive()
    await db.commit()
    return {"message": "Auth Assistant device revoked", "device": _serialize_device(device)}


@router.post("/auth-bundles/import")
async def import_auth_bundle_from_assistant(
    request_body: AuthAssistantBundleImportRequest,
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_auth_assistant_token: str | None = Depends(_device_token_header),
    db: AsyncSession = Depends(get_async_db),
):
    device = await require_auth_assistant_device(db, authorization, x_auth_assistant_token)
    try:
        result = await import_auth_bundle(
            db,
            request_body.bundle,
            name=request_body.name,
            bind_matching_sources=request_body.bind_matching_sources,
            create_browser_session=request_body.create_browser_session,
        )
    except AuthBundleError as exc:
        await _record_import_log(db, device, None, None, str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    response = await _serialize_import_result(db, result)
    await _record_import_log(db, device, result.get("site_host"), response, None)
    await db.commit()
    return response


@router.post("/auth-exports/import")
async def import_auth_export_zip_from_assistant(
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_auth_assistant_token: str | None = Depends(_device_token_header),
    db: AsyncSession = Depends(get_async_db),
):
    device = await require_auth_assistant_device(db, authorization, x_auth_assistant_token)
    payload = await file.read()
    bundles = _read_auth_export_payload(payload)
    imported: list[dict[str, Any]] = []
    warnings: list[str] = []
    for bundle in bundles:
        try:
            result = await import_auth_bundle(db, bundle, bind_matching_sources=True, create_browser_session=True)
        except AuthBundleError as exc:
            warnings.append(str(exc))
            continue
        imported.append(await _serialize_import_result(db, result))

    response = {
        "imported_profiles": len(imported),
        "profiles": imported,
        "warnings": warnings,
    }
    await _record_import_log(db, device, None, response, "; ".join(warnings) if warnings else None)
    await db.commit()
    return response


def _auth_assistant_capabilities() -> dict[str, bool]:
    return {
        "import_bundle": True,
        "import_zip": True,
        "verify_auth": False,
        "bind_sources": True,
    }


def _serialize_device(device: AuthAssistantDevice) -> dict[str, Any]:
    return {
        "id": str(device.id),
        "name": device.name,
        "status": device.status.value if hasattr(device.status, "value") else str(device.status),
        "app_version": device.app_version,
        "last_seen_at": device.last_seen_at.isoformat() + "Z" if device.last_seen_at else None,
        "created_at": device.created_at.isoformat() + "Z" if device.created_at else None,
        "revoked_at": device.revoked_at.isoformat() + "Z" if device.revoked_at else None,
        "capabilities": device.capabilities or {},
    }


async def _serialize_import_result(db: AsyncSession, result: dict[str, Any]) -> dict[str, Any]:
    auth_result = await db.execute(
        select(AuthConfig)
        .options(selectinload(AuthConfig.sources))
        .where(AuthConfig.id == result["auth_config"].id)
    )
    auth_config = auth_result.scalar_one()
    browser_session = result.get("browser_session")
    return {
        "site_host": result["site_host"],
        "cookie_count": result["cookie_count"],
        "storage_state_imported": result["storage_state_imported"],
        "bound_sources": result["bound_sources"],
        "auth_config": serialize_auth_config(auth_config),
        "browser_session": (
            {
                "id": str(browser_session.id),
                "site_host": browser_session.site_host,
                "status": browser_session.status.value if hasattr(browser_session.status, "value") else str(browser_session.status),
                "storage_state_path": browser_session.storage_state_path,
            }
            if browser_session
            else None
        ),
    }


async def _record_import_log(
    db: AsyncSession,
    device: AuthAssistantDevice,
    site_host: str | None,
    result: dict[str, Any] | None,
    error: str | None,
) -> None:
    db.add(
        AuthAssistantImportLog(
            device_id=device.id,
            site_host=site_host,
            profile_count=str(result.get("imported_profiles", 1) if result else 0),
            result=result or {},
            error=error,
        )
    )


def _read_auth_export_payload(payload: bytes) -> list[dict[str, Any]]:
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if manifest.get("kind") != _AUTH_EXPORT_KIND:
                raise HTTPException(status_code=422, detail="Unsupported auth export kind")
            bundles: list[dict[str, Any]] = []
            for item in manifest.get("profiles") or []:
                profile_path = item.get("file") if isinstance(item, dict) else None
                if not profile_path:
                    continue
                bundle = json.loads(archive.read(profile_path).decode("utf-8"))
                if bundle.get("kind") == _AUTH_BUNDLE_KIND:
                    bundles.append(bundle)
            if not bundles:
                raise HTTPException(status_code=422, detail="Auth export zip contains no auth bundles")
            return bundles
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"Auth export zip missing file: {exc}") from exc
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=422, detail="Uploaded file is not a valid zip") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Auth export zip contains invalid JSON") from exc
