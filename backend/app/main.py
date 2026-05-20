"""FastAPI application entry point."""

import asyncio
import os
import re
import secrets as _secrets
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from html import escape as _html_escape

from app.api import api_router
from app.auth import verify_api_key
from app.config import bootstrap_runtime_environment, get_settings, parse_cors_origins
from app.database import async_engine
from app.migrations import run_migrations
from app.middleware.api_rate_limit import APIRateLimitMiddleware, get_real_client_ip
from app.platform.health import health_router
from app.utils.logger import clear_request_id, get_logger, set_request_id
from app.utils.metrics import persist_metrics, request_metrics, restore_metrics

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


def _mask_secret(value: str, prefix: int = 4, suffix: int = 4) -> str:
    text = (value or "").strip()
    if not text:
        return "(not set)"
    if len(text) <= prefix + suffix:
        return "*" * len(text)
    return f"{text[:prefix]}...{text[-suffix:]}"


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    if os.environ.get("PIM_SKIP_MIGRATIONS", "").strip().lower() in {"1", "true", "yes", "on"}:
        logger.warning(
            "PIM_SKIP_MIGRATIONS is set — skipping Alembic migrations (development only; unsafe in production)"
        )
    else:
        await asyncio.to_thread(run_migrations)

    # Restore persisted metrics counters so rate() queries survive restarts.
    try:
        if restore_metrics():
            logger.info("Restored persisted metrics counters from data_dir checkpoint")
    except Exception as exc:  # noqa: BLE001 - observability best-effort
        logger.warning("Failed to restore metrics checkpoint: %s", exc)

    # Start scheduler
    from app.scheduler import scheduler, setup_scheduler, trigger_startup_jobs
    setup_scheduler()
    scheduler.start()
    trigger_startup_jobs()

    # Start bounded task queue workers. Handlers are injected here so the
    # platform.workers.queue module stays free of any business-domain
    # imports (Phase 5 step 9 — eliminates platform → domains violation).
    from app.domains.ingest.finish import finish_content
    from app.tasks.fetch_tasks import fetch_source
    from app.tasks.task_queue import task_queue

    async def _fetch_handler(source_id: str, manual_trigger: bool) -> None:
        await fetch_source(source_id, manual_trigger=manual_trigger)

    async def _process_handler(content_id: str, job_id: str | None) -> None:
        await finish_content(content_id, job_id=job_id)

    await task_queue.start_workers(
        fetch_handler=_fetch_handler,
        process_handler=_process_handler,
    )

    # Print startup info
    print(f"\n  PIM API Key: {_mask_secret(settings.pim_api_key)}")
    print(f"  Data dir:    {settings.data_dir}")
    print(f"  Fetch concurrency: {settings.fetch_concurrency}")
    _enrich_flags = (
        f"auto_on_ingest={settings.enrich_auto_on_ingest}, "
        f"summary={settings.enrich_summary_enabled}, "
        f"translate={settings.enrich_translate_enabled}"
    )
    print(
        "  AI processing: "
        f"{'enabled' if settings.ai_processing_enabled else 'disabled'} "
        f"(enrich: {_enrich_flags})"
    )
    print(
        "  Bootstrap URL (web auto-provision): run `./pim bootstrap-url` to print"
    )
    print()

    if settings.probe_disable_ssl_verify and settings.debug:
        logger.warning(
            "SECURITY WARNING: probe_disable_ssl_verify=True — SSL certificate verification is "
            "disabled for all outbound probe/fetch requests. This should never be enabled in "
            "production as it exposes the service to man-in-the-middle attacks."
        )
    elif settings.probe_disable_ssl_verify:
        logger.warning(
            "Ignoring probe_disable_ssl_verify because debug mode is disabled; outbound probe/fetch "
            "requests will continue to verify SSL certificates."
        )

    # Surface feature-flag posture so operators notice unsafe defaults in logs
    # without needing to hit /api/system/doctor first.
    from app.features import playwright_enabled, x_playwright_enabled

    if not playwright_enabled():
        logger.warning(
            "PIM_FEATURE_PLAYWRIGHT is disabled — JS-heavy site collection and "
            "cookie-login bootstrap will be skipped. Enable with PIM_FEATURE_PLAYWRIGHT=true."
        )
    else:
        logger.info("Playwright feature is enabled (PIM_FEATURE_PLAYWRIGHT=true).")
    if x_playwright_enabled():
        logger.warning(
            "PIM_FEATURE_X_PLAYWRIGHT=true — X (Twitter) logged-in Chromium hydration is active. "
            "This feature touches X Terms of Service grey area (ADR-003); keep it off unless "
            "you fully understand the risk."
        )

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    await task_queue.stop_workers()

    # Release the shared Playwright/Chromium process before dropping the DB
    # engine so we never leak a Chromium child on graceful reload.
    try:
        from app.utils.browser import shutdown_browser_pool

        await shutdown_browser_pool()
    except Exception as exc:
        logger.warning("Browser pool shutdown raised: %s", exc)

    # Checkpoint metrics counters before dropping the process.
    try:
        if persist_metrics() is not None:
            logger.info("Persisted metrics counters to data_dir checkpoint")
    except Exception as exc:  # noqa: BLE001 - observability best-effort
        logger.warning("Failed to persist metrics checkpoint: %s", exc)

    await async_engine.dispose()


app = FastAPI(
    title=settings.app_name,
    description="个人化资讯监控管理系统 API",
    version="2.0.0",
    lifespan=lifespan,
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


_ALLOWED_LOCAL_TOKEN_HOSTNAMES = frozenset(
    {"127.0.0.1", "localhost", "::1", "[::1]"}
)

_BOOTSTRAP_META_NAME = "pim-bootstrap-token"


def _inject_bootstrap_meta(html: str, request: Request, token: str) -> str:
    """Stamp the bootstrap token into index.html for trusted loopback callers.

    This is the single-machine-user shortcut that lets the SPA acquire its API
    key without asking the user to type one. Callers that don't match the same
    defence-in-depth gate as ``/local-token`` (loopback IP + allowed Host) get
    the page back unchanged, so remote or Host-spoofed requests continue to
    fall through to the manual prompt.
    """
    clean_token = (token or "").strip()
    if not clean_token:
        return html
    try:
        real_ip = get_real_client_ip(request)
    except Exception:
        return html
    if real_ip not in ("127.0.0.1", "::1"):
        return html
    hostname = _hostname_of(request.headers.get("host"))
    if hostname not in _ALLOWED_LOCAL_TOKEN_HOSTNAMES:
        return html
    meta_tag = (
        f'<meta name="{_BOOTSTRAP_META_NAME}" '
        f'content="{_html_escape(clean_token, quote=True)}">'
    )
    if "</head>" in html:
        return html.replace("</head>", f"    {meta_tag}\n  </head>", 1)
    return meta_tag + html


def _hostname_of(host_header: str | None) -> str:
    """Strip an optional ``:port`` from a Host header and lower-case."""
    value = (host_header or "").strip().lower()
    if not value:
        return ""
    # IPv6 literal like "[::1]:8000"
    if value.startswith("["):
        closing = value.find("]")
        if closing == -1:
            return value
        return value[: closing + 1]
    # host:port
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


def _origin_is_permitted(origin: str | None) -> bool:
    """Only same-site or Tauri origins may call the bootstrap endpoint."""
    candidate = (origin or "").strip().lower()
    if not candidate:
        # Missing Origin (e.g. curl / server-side call) is acceptable; the other
        # checks (loopback, Host, bootstrap_token) still protect the endpoint.
        return True
    if candidate == "tauri://localhost":
        return True
    allowed = {item.lower() for item in parse_cors_origins(settings.cors_origins)}
    return candidate in allowed


def _bootstrap_token_matches(request: Request) -> bool:
    expected = (settings.bootstrap_token or "").strip()
    if not expected:
        # Fail closed: a misconfigured server should not hand out API keys.
        return False

    header_token = request.headers.get("X-Bootstrap-Token", "")
    query_token = request.query_params.get("bootstrap_token", "")
    for provided in (header_token, query_token):
        provided = (provided or "").strip()
        if provided and _secrets.compare_digest(provided, expected):
            return True
    return False


@app.get("/local-token")
async def local_token(request: Request):
    """Return the API key for trusted local callers only.

    Defence-in-depth gates — every request must pass all of them:

    1. Source IP must be loopback (or the configured trusted proxy).
    2. ``Host`` header hostname must be ``localhost`` / ``127.0.0.1`` / ``::1``
       to block DNS rebinding attacks where a malicious site forces the
       browser to send requests to the loopback interface under its own domain.
    3. ``Origin`` header, if present, must be a CORS-whitelisted origin or
       ``tauri://localhost``. ``null`` / other origins are rejected.
    4. A ``bootstrap_token`` (query string or ``X-Bootstrap-Token`` header)
       must match the value stored in ``runtime-secrets.json``. The token is
       distributed out-of-band via the filesystem (mode 0600) to the Tauri
       shell and operator CLI, and is never echoed over HTTP.

    Result: the endpoint is safe even when another unprivileged process on the
    same host tries to scrape it, because the attacker cannot read the
    0600-protected bootstrap token file.
    """
    real_ip = get_real_client_ip(request)
    if real_ip not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Local access only")

    hostname = _hostname_of(request.headers.get("host"))
    if hostname not in _ALLOWED_LOCAL_TOKEN_HOSTNAMES:
        logger.warning("/local-token rejected: invalid Host header %r", request.headers.get("host"))
        raise HTTPException(status_code=403, detail="Invalid host")

    if not _origin_is_permitted(request.headers.get("origin")):
        logger.warning("/local-token rejected: invalid Origin %r", request.headers.get("origin"))
        raise HTTPException(status_code=403, detail="Invalid origin")

    if not _bootstrap_token_matches(request):
        logger.warning("/local-token rejected: missing or invalid bootstrap token")
        raise HTTPException(status_code=401, detail="Missing or invalid bootstrap token")

    return {"api_key": settings.pim_api_key}


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

        html = _inject_bootstrap_meta(html, request, settings.bootstrap_token)
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
            "version": "2.0.0",
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
