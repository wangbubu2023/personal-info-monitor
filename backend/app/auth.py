"""API Key authentication for PIM API endpoints."""

import secrets

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Security(_api_key_header)) -> str:
    """Dependency that validates the X-API-Key header.

    Returns the validated key on success; raises 401 otherwise.
    """
    settings = get_settings()
    expected = settings.pim_api_key
    if not expected:
        raise HTTPException(status_code=500, detail="Server misconfigured: API key not set")
    if not api_key or not secrets.compare_digest(api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key
