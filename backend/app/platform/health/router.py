"""Liveness and detailed-health HTTP endpoints.

Previously lived inline in :mod:`app.main` (Phase 5 step 12 extracted them
into the platform layer). Mounting is done by :mod:`app.main` via
``app.include_router(health_router)``.
"""

from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.platform.auth.api_key import verify_api_key
from app.platform.config.settings import get_settings
from app.platform.observability.logger import get_logger
from app.platform.persistence.database import async_engine

logger = get_logger(__name__)
_settings = get_settings()

health_router = APIRouter(tags=["health"])


@health_router.get("/livez")
async def livez() -> dict[str, str]:
    """Public liveness probe for local tooling and desktop bootstrap."""
    return {"status": "ok"}


@health_router.get("/health", dependencies=[Depends(verify_api_key)])
async def health_check() -> JSONResponse:
    """Detailed health check endpoint for authenticated operators."""
    checks: dict[str, str] = {}
    details: dict[str, object] = {}

    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 — log+degrade, never propagate
        checks["database"] = "error"
        logger.warning("Database health check failed: %s", exc)

    try:
        from app.scheduler import scheduler

        checks["scheduler"] = "ok" if getattr(scheduler, "running", False) else "error"
        details["scheduled_jobs"] = len(scheduler.get_jobs())
    except Exception as exc:  # noqa: BLE001 — log+degrade, never propagate
        checks["scheduler"] = "error"
        logger.warning("Scheduler health check failed: %s", exc)

    try:
        usage = shutil.disk_usage(_settings.data_dir)
        details["disk_free_bytes"] = usage.free
        checks["disk"] = "ok" if usage.free >= 100 * 1024 * 1024 else "error"
    except Exception as exc:  # noqa: BLE001 — log+degrade, never propagate
        checks["disk"] = "error"
        logger.warning("Disk health check failed: %s", exc)

    healthy = all(value == "ok" for value in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "healthy" if healthy else "degraded",
            "checks": checks,
            "details": details,
        },
    )
