"""API Key authentication for PIM API endpoints."""

import secrets

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from app.platform.config.settings import get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(
    api_key: str | None = Security(_api_key_header),
    request: Request = None,  # type: ignore[assignment]
) -> str:
    """Dependency that validates the X-API-Key header.

    Returns the validated key on success; raises 401 otherwise.
    """
    settings = get_settings()
    expected = settings.pim_api_key
    if not expected:
        raise HTTPException(status_code=500, detail="Server misconfigured: API key not set")
    if api_key and secrets.compare_digest(api_key, expected):
        return api_key

    if request is not None:
        from app.platform.auth.web_session import SESSION_COOKIE_NAME, validate_web_session

        actor = validate_web_session(request.cookies.get(SESSION_COOKIE_NAME, ""))
        if actor is not None:
            return f"session:{actor}"
    raise HTTPException(status_code=401, detail="Invalid or missing API key or session")
