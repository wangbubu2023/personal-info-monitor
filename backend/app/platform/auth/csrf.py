"""Double-submit CSRF token and strict browser origin validation."""

from __future__ import annotations

import secrets

from fastapi import Request

from app.config import effective_cors_origins, get_settings

CSRF_COOKIE_NAME = "pim_csrf"
CSRF_HEADER_NAME = "X-PIM-CSRF"
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def issue_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def origin_allowed(origin: str | None) -> bool:
    value = str(origin or "").strip().lower()
    if not value:
        return False
    if value == "tauri://localhost":
        return True
    return value in {item.lower() for item in effective_cors_origins(get_settings())}


def csrf_request_is_valid(request: Request) -> bool:
    if request.method.upper() not in _UNSAFE_METHODS:
        return True
    origin = request.headers.get("origin")
    if origin and not origin_allowed(origin):
        return False
    cookie = str(request.cookies.get(CSRF_COOKIE_NAME) or "")
    header = str(request.headers.get(CSRF_HEADER_NAME) or "")
    return bool(cookie and header and secrets.compare_digest(cookie, header))
