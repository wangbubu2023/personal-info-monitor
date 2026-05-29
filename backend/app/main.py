"""FastAPI application entry point."""

import os
import re
from time import perf_counter
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse

from app.api import api_router
from app.auth import verify_api_key
from app.config import bootstrap_runtime_environment, get_settings, parse_cors_origins
from app.middleware.api_rate_limit import APIRateLimitMiddleware
from app.platform.auth import bootstrap_router, inject_bootstrap_meta
from app.platform.health import health_router
from app.platform.runtime import build_lifespan
from app.utils.logger import clear_request_id, get_logger, set_request_id
from app.utils.metrics import request_metrics

bootstrap_runtime_environment()
settings = get_settings()
logger = get_logger(__name__)
DEFAULT_API_PORT = 8000
DEV_FRONTEND_URL = os.getenv("PIM_DEV_FRONTEND_URL", "http://127.0.0.1:3000").strip() or "http://127.0.0.1:3000"
DEV_SERVER_MODE = os.getenv("PIM_DEV_SERVER", "").strip().lower() in {"1", "true", "yes"}
SPA_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

# Security headers applied to every SPA HTML response. We keep CSP lenient enough
# that Ant Design's runtime-injected <style> tags and Google Fonts continue to
# work, but block script sources we never legitimately pull from.
_SPA_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' http://127.0.0.1:8000 http://localhost:8000; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
}
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def _normalize_request_id(raw_value: str | None) -> str:
    candidate = (raw_value or "").strip()
    if _REQUEST_ID_RE.fullmatch(candidate):
        return candidate
    return uuid4().hex


def _request_route_label(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None:
        path_format = getattr(route, "path_format", None)
        if isinstance(path_format, str) and path_format:
            return path_format
        path = getattr(route, "path", None)
        if isinstance(path, str) and path:
            return path
    return request.url.path or "/"


# Composition root: pick the concrete domain handlers and hand them to the
# platform-level lifespan factory so platform/runtime stays free of any
# app.domains.* imports (Phase 5 step 13 — preserves the platform ↛ domains
# invariant enforced by scripts/check_domain_imports.py --phase=5).
from app.domains.ingest.finish import finish_content
from app.tasks.fetch_tasks import fetch_source


async def _fetch_handler(source_id: str, manual_trigger: bool) -> None:
    await fetch_source(source_id, manual_trigger=manual_trigger)


async def _process_handler(content_id: str, job_id: str | None) -> None:
    await finish_content(content_id, job_id=job_id)


app = FastAPI(
    title=settings.app_name,
    description="个人化资讯监控管理系统 API",
    version="1.0.3",
    lifespan=build_lifespan(
        fetch_handler=_fetch_handler,
        process_handler=_process_handler,
    ),
)

# CORS: browser dev + Tauri WebView
app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_cors_origins(settings.cors_origins),
    allow_origin_regex=r"^tauri://localhost$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

app.add_middleware(
    APIRateLimitMiddleware,
    requests_per_minute=settings.api_rate_limit_per_minute,
    local_token_requests_per_minute=settings.local_token_rate_limit_per_minute,
)

# Include API routes
app.include_router(api_router, prefix="/api")
# Platform-level health/liveness endpoints (extracted from this module in Phase 5.12).
app.include_router(health_router)
# /local-token endpoint + SPA bootstrap-meta helpers (extracted in Phase 5.14).
app.include_router(bootstrap_router)


@app.middleware("http")
async def request_observability_middleware(request: Request, call_next):
    """Attach request ids and basic latency metrics to every request."""
    request_id = _normalize_request_id(request.headers.get("X-Request-ID"))
    set_request_id(request_id)
    started = perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (perf_counter() - started) * 1000
        request_metrics.record(
            method=request.method,
            path=_request_route_label(request),
            status_code=500,
            duration_ms=duration_ms,
        )
        logger.exception("Unhandled request error")
        clear_request_id()
        raise

    duration_ms = (perf_counter() - started) * 1000
    request_metrics.record(
        method=request.method,
        path=_request_route_label(request),
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
    response.headers["X-Request-ID"] = request_id
    clear_request_id()
    return response


@app.get("/metrics", dependencies=[Depends(verify_api_key)], response_class=PlainTextResponse)
async def prometheus_metrics():
    """Prometheus-compatible metrics endpoint for authenticated operators."""
    from app.api.system import get_metrics_prometheus

    return get_metrics_prometheus()


# Serve Frontend Static Files (SPA Fallback)
dist_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend", "dist")

if os.path.isdir(dist_dir) and not DEV_SERVER_MODE:
    from fastapi.staticfiles import StaticFiles
    assets_dir = os.path.join(dist_dir, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    _INDEX_HTML_PATH = os.path.join(dist_dir, "index.html")

    def _render_index_html(request: Request) -> HTMLResponse:
        """Serve index.html, stamping the bootstrap token for trusted local callers.

        The /local-token endpoint hands the API key to any caller that can present
        the bootstrap_token (a 0600-owned secret). On a single-machine install the
        browser has no natural way to obtain that token, which is why visiting
        http://localhost:8000 used to always trigger a manual "请输入 PIM API Key"
        prompt. We now inline the bootstrap token into the SPA shell for loopback
        callers with an allowed Host header; the frontend reads it, silently
        calls /local-token, and persists the returned API key. Remote callers
        and Host-header spoof attempts still receive a clean index.html with no
        token, preserving the existing defence-in-depth.
        """
        try:
            with open(_INDEX_HTML_PATH, "r", encoding="utf-8") as fh:
                html = fh.read()
        except OSError:
            return FileResponse(
                _INDEX_HTML_PATH,
                headers={**SPA_NO_CACHE_HEADERS, **_SPA_SECURITY_HEADERS},
            )

        html = inject_bootstrap_meta(html, request, settings.bootstrap_token)
        return HTMLResponse(
            content=html,
            headers={**SPA_NO_CACHE_HEADERS, **_SPA_SECURITY_HEADERS},
        )

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str, request: Request):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")

        # Security: prevent directory traversal
        file_path = os.path.join(dist_dir, full_path)
        resolved = os.path.realpath(file_path)
        if not resolved.startswith(os.path.realpath(dist_dir)):
            raise HTTPException(status_code=403, detail="Forbidden")

        if full_path and os.path.isfile(resolved):
            if resolved == os.path.realpath(_INDEX_HTML_PATH):
                return _render_index_html(request)
            headers = (
                {**SPA_NO_CACHE_HEADERS, **_SPA_SECURITY_HEADERS}
                if resolved.endswith(".html")
                else None
            )
            return FileResponse(resolved, headers=headers)

        return _render_index_html(request)
else:
    @app.get("/")
    async def root():
        status = "running (Frontend dist not found — run: cd frontend && npm run build)"
        if DEV_SERVER_MODE:
            status = f"running (Frontend dev server: {DEV_FRONTEND_URL})"
        return {
            "name": settings.app_name,
            "version": "1.0.3",
            "status": status,
        }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=DEFAULT_API_PORT,
        reload=settings.debug
    )
