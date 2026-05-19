"""Per-client sliding-window rate limit for /api routes (in-process)."""

from __future__ import annotations

import os
import time
from collections import defaultdict
from functools import lru_cache

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


_MAX_TRACKED_KEYS = 10_000  # Guard against memory exhaustion from spoofed IPs


@lru_cache(maxsize=1)
def _trusted_proxy_ips() -> frozenset[str]:
    """Return the set of trusted reverse-proxy IPs from TRUSTED_PROXY_IPS env var.

    Set TRUSTED_PROXY_IPS to a comma-separated list of proxy IPs (e.g. ``127.0.0.1``)
    when running behind nginx/Caddy so the real client IP is read from X-Real-IP.
    """
    raw = os.environ.get("TRUSTED_PROXY_IPS", "")
    return frozenset(ip.strip() for ip in raw.split(",") if ip.strip())


def get_real_client_ip(request: Request) -> str:
    """Return the real client IP.

    When the connecting host is in TRUSTED_PROXY_IPS, the value of the
    ``X-Real-IP`` header (set by nginx/Caddy) is returned instead.
    Falls back to ``request.client.host`` for direct connections.
    """
    client_ip = request.client.host if request.client else ""
    trusted = _trusted_proxy_ips()
    if trusted and client_ip in trusted:
        real_ip = request.headers.get("X-Real-IP", "").strip()
        if real_ip:
            return real_ip
    return client_ip


class APIRateLimitMiddleware(BaseHTTPMiddleware):
    """Limit requests per minute per client key (IP + API key prefix).

    ``requests_per_minute <= 0`` disables limiting.
    Caps tracked key count at ``_MAX_TRACKED_KEYS`` to bound memory usage.
    """

    def __init__(
        self,
        app,
        requests_per_minute: int,
        *,
        local_token_requests_per_minute: int = 30,
    ) -> None:
        super().__init__(app)
        self._rpm = int(requests_per_minute)
        self._local_token_rpm = int(local_token_requests_per_minute)
        self._windows: dict[str, list[float]] = defaultdict(list)
        self._window_seconds = 60.0

    async def dispatch(self, request: Request, call_next):
        path = request.url.path or ""
        normalized = path.rstrip("/") or "/"

        if normalized == "/local-token":
            if self._local_token_rpm <= 0:
                return await call_next(request)
            lt_key = f"{get_real_client_ip(request) or 'unknown'}:__local_token__"
            return await self._enforce(request, call_next, rpm=self._local_token_rpm, key=lt_key)

        if self._rpm <= 0:
            return await call_next(request)
        if not path.startswith("/api"):
            return await call_next(request)
        return await self._enforce(request, call_next, rpm=self._rpm, key=self._client_key(request))

    async def _enforce(self, request: Request, call_next, *, rpm: int, key: str) -> Response:
        now = time.monotonic()
        window_start = now - self._window_seconds

        if len(self._windows) >= _MAX_TRACKED_KEYS and key not in self._windows:
            self._evict_stale(now)

        stamps = self._windows[key]
        stamps[:] = [t for t in stamps if t > window_start]

        if len(stamps) >= rpm:
            return JSONResponse(
                {"detail": "Too many requests. Try again later."},
                status_code=429,
                headers={"Retry-After": "60"},
            )

        stamps.append(now)
        return await call_next(request)

    def _evict_stale(self, now: float) -> None:
        """Remove keys whose sliding window is entirely expired."""
        window_start = now - self._window_seconds
        stale = [k for k, stamps in self._windows.items() if not any(t > window_start for t in stamps)]
        for k in stale:
            del self._windows[k]

    @staticmethod
    def _client_key(request: Request) -> str:
        ip = get_real_client_ip(request) or "unknown"
        api_key = (request.headers.get("X-API-Key") or "").strip()
        key_hint = api_key[:12] if api_key else "-"
        return f"{ip}:{key_hint}"
