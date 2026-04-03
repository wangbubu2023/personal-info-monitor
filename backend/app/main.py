"""FastAPI application entry point."""

import asyncio
import os
import shutil
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from sqlalchemy import text

from app.api import api_router
from app.auth import verify_api_key
from app.config import bootstrap_runtime_environment, get_settings, parse_cors_origins
from app.database import async_engine
from app.migrations import run_migrations
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


def _mask_secret(value: str, prefix: int = 4, suffix: int = 4) -> str:
    text = (value or "").strip()
    if not text:
        return "(not set)"
    if len(text) <= prefix + suffix:
        return "*" * len(text)
    return f"{text[:prefix]}...{text[-suffix:]}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Apply DB migrations before serving traffic.
    await asyncio.to_thread(run_migrations)

    # Start scheduler
    from app.scheduler import scheduler, setup_scheduler, trigger_startup_jobs
    setup_scheduler()
    scheduler.start()
    trigger_startup_jobs()

    # Start bounded task queue workers
    from app.tasks.task_queue import task_queue
    await task_queue.start_workers()

    # Print startup info
    print(f"\n  PIM API Key: {_mask_secret(settings.pim_api_key)}")
    print(f"  Data dir:    {settings.data_dir}")
    print(f"  Fetch concurrency: {settings.fetch_concurrency}")
    print(f"  AI processing: {'enabled' if settings.ai_processing_enabled else 'disabled'}")
    print()

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    await task_queue.stop_workers()
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

# Include API routes
app.include_router(api_router, prefix="/api")


@app.middleware("http")
async def request_observability_middleware(request: Request, call_next):
    """Attach request ids and basic latency metrics to every request."""
    request_id = (request.headers.get("X-Request-ID") or "").strip() or uuid4().hex
    set_request_id(request_id)
    started = perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (perf_counter() - started) * 1000
        request_metrics.record(
            method=request.method,
            path=request.url.path,
            status_code=500,
            duration_ms=duration_ms,
        )
        logger.exception("Unhandled request error")
        clear_request_id()
        raise

    duration_ms = (perf_counter() - started) * 1000
    request_metrics.record(
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
    response.headers["X-Request-ID"] = request_id
    clear_request_id()
    return response


@app.get("/livez")
async def livez():
    """Public liveness probe for local tooling and desktop bootstrap."""
    return {"status": "ok"}


@app.get("/health", dependencies=[Depends(verify_api_key)])
async def health_check():
    """Detailed health check endpoint for authenticated operators."""
    checks = {}
    details = {}

    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = "error"
        logger.warning("Database health check failed: %s", exc)

    try:
        from app.scheduler import scheduler

        checks["scheduler"] = "ok" if getattr(scheduler, "running", False) else "error"
        details["scheduled_jobs"] = len(scheduler.get_jobs())
    except Exception as exc:
        checks["scheduler"] = "error"
        logger.warning("Scheduler health check failed: %s", exc)

    try:
        usage = shutil.disk_usage(settings.data_dir)
        details["disk_free_bytes"] = usage.free
        checks["disk"] = "ok" if usage.free >= 100 * 1024 * 1024 else "error"
    except Exception as exc:
        checks["disk"] = "error"
        logger.warning("Disk health check failed: %s", exc)

    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "healthy" if healthy else "degraded",
            "checks": checks,
            "details": details,
        },
    )


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

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")

        # Security: prevent directory traversal
        file_path = os.path.join(dist_dir, full_path)
        resolved = os.path.realpath(file_path)
        if not resolved.startswith(os.path.realpath(dist_dir)):
            raise HTTPException(status_code=403, detail="Forbidden")

        if full_path and os.path.isfile(resolved):
            headers = SPA_NO_CACHE_HEADERS if resolved.endswith(".html") else None
            return FileResponse(resolved, headers=headers)

        return FileResponse(os.path.join(dist_dir, "index.html"), headers=SPA_NO_CACHE_HEADERS)
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
