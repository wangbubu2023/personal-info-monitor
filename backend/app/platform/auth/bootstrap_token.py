"""One-time Web bootstrap exchange and HttpOnly session lifecycle.

The old ``/local-token`` contract returned a long-lived API key and accepted a
long-lived token from HTML/meta/query/header. It is intentionally retired: Web
clients now exchange a short, single-use code from a JSON request body and only
receive an HttpOnly session cookie.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.platform.auth.web_session import (
    SESSION_COOKIE_NAME,
    exchange_bootstrap_code,
    revoke_web_session,
    rotate_web_session,
    validate_web_session,
)
from app.platform.config.settings import effective_cors_origins, get_settings
from app.platform.observability.logger import get_logger

logger = get_logger(__name__)
bootstrap_router = APIRouter(tags=["bootstrap"])


class BootstrapExchangeRequest(BaseModel):
    code: str = Field(min_length=16, max_length=256)


def _origin_is_permitted(origin: str | None) -> bool:
    candidate = (origin or "").strip().lower()
    if not candidate:
        return True
    if candidate == "tauri://localhost":
        return True
    return candidate in {item.lower() for item in effective_cors_origins(get_settings())}


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=7 * 24 * 60 * 60,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


@bootstrap_router.post("/bootstrap/exchange")
async def bootstrap_exchange(payload: BootstrapExchangeRequest, request: Request, response: Response):
    if not _origin_is_permitted(request.headers.get("origin")):
        raise HTTPException(status_code=403, detail="Invalid origin")
    issued = exchange_bootstrap_code(payload.code)
    if issued is None:
        logger.warning("Bootstrap code exchange rejected")
        raise HTTPException(status_code=401, detail="Bootstrap code is invalid, expired, used, or revoked")
    _set_session_cookie(response, issued.token)
    return {"status": "authenticated", "actor": issued.actor, "session_id": issued.session_id}


@bootstrap_router.post("/bootstrap/session/rotate")
async def rotate_session(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    if validate_web_session(token, touch=False) is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    issued = rotate_web_session(token)
    if issued is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    _set_session_cookie(response, issued.token)
    return {"status": "rotated", "session_id": issued.session_id}


@bootstrap_router.get("/bootstrap/session")
async def session_status(request: Request):
    if not getattr(get_settings(), "pim_web_auth_required", True):
        return {"status": "not_required", "actor": "same-origin-browser"}
    actor = validate_web_session(request.cookies.get(SESSION_COOKIE_NAME, ""))
    if actor is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return {"status": "authenticated", "actor": actor}


@bootstrap_router.post("/bootstrap/session/logout")
async def logout_session(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    revoke_web_session(token)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return {"status": "revoked"}


@bootstrap_router.get("/local-token")
async def retired_local_token_get():
    raise HTTPException(status_code=410, detail="Long-lived token bootstrap has been retired")


@bootstrap_router.post("/local-token")
async def retired_local_token_post():
    raise HTTPException(status_code=410, detail="Long-lived token bootstrap has been retired")


def inject_bootstrap_meta(html: str, request: Request, token: str) -> str:
    """Compatibility no-op: secrets must never be injected into HTML."""
    return html


_inject_bootstrap_meta = inject_bootstrap_meta


__all__ = ["bootstrap_router", "inject_bootstrap_meta"]
