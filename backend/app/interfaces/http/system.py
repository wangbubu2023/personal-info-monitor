"""System and queue status API."""

import asyncio
from typing import Any, Dict, List

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, Response

from app.background import task_tracker
from app.config import get_settings
from app.platform.config.settings import effective_fetch_concurrency
from app.domains.sources.monitoring import MonitorService
from app.domains.sources.source_types import source_type_catalog
from app.database import SessionLocal
from app.scheduler import scheduler
from app.utils.logger import get_logger
from app.utils.metrics import reliability_metrics, request_metrics, source_metrics, storage_metrics, task_queue_metrics

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter()


def _get_sources_status_sync() -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        svc = MonitorService(db)
        return svc.get_all_sources_status()
    finally:
        db.close()


@router.get("/queue")
def get_queue_status() -> Dict[str, Any]:
    """Get task and fetch status for observability."""
    status = task_tracker.status()
    try:
        sources_status = _get_sources_status_sync()
    except Exception as e:
        logger.warning(f"Failed to get sources status: {e}")
        sources_status = []

    try:
        from app.platform.workers.postprocess_jobs import postprocess_completion_rate

        postprocess = postprocess_completion_rate()
    except Exception as e:
        logger.warning("Failed to get postprocess job metrics: %s", e)
        postprocess = {"total": 0, "succeeded": 0, "failed": 0, "completion_rate": 1.0}

    return {
        "running_fetches": status["running_fetches"],
        "running_processes": status["running_processes"],
        "fetch_concurrency": settings.fetch_concurrency,
        "active_fetch_concurrency": effective_fetch_concurrency(settings),
        "fetch_active_limit": getattr(settings, "fetch_active_limit", 20),
        "scheduler_running": bool(getattr(scheduler, "running", False)),
        "scheduled_jobs": len(scheduler.get_jobs()),
        "postprocess_jobs": postprocess,
        "sources_status": sources_status,
    }


@router.get("/features")
def get_runtime_features() -> Dict[str, Any]:
    """Expose static + env-driven feature flags for clients."""
    from app import features as feat

    return {
        "podcast_sources_enabled": feat.PODCAST_SOURCES_ENABLED,
        "keyword_monitoring_enabled": feat.KEYWORD_MONITORING_ENABLED,
        "playwright_enabled": feat.playwright_enabled(),
        "x_playwright_enabled": feat.x_playwright_enabled(),
        "atoms_enabled": feat.atoms_product_enabled() and feat.atoms_enabled(),
        "atoms_relations_enabled": feat.atoms_product_enabled() and feat.atoms_relations_enabled(),
        "atoms_reconcile_enabled": feat.atoms_product_enabled() and feat.atoms_reconcile_enabled(),
        "atoms_knowledge_enabled": feat.atoms_product_enabled() and feat.atoms_knowledge_enabled(),
        "atoms_frozen": not feat.atoms_product_enabled(),
    }


@router.get("/source-types")
def get_source_types(include_disabled: bool = False) -> Dict[str, Any]:
    """Return the canonical source-type catalog.

    Single source of truth for UI dropdowns / tabs / prompt lists — clients
    should call this at startup and reuse the bundled copy as a fallback.
    """
    catalog = source_type_catalog(include_disabled=include_disabled)
    return {"items": [info.to_dict() for info in catalog]}


@router.get("/metrics")
def get_metrics() -> Dict[str, Any]:
    """Expose lightweight runtime metrics for local observability."""
    payload = request_metrics.snapshot()
    payload["sources"] = source_metrics.snapshot()
    payload["storage"] = storage_metrics.snapshot()
    payload["reliability"] = reliability_metrics.snapshot()
    payload["scheduler"] = {
        "running": bool(getattr(scheduler, "running", False)),
        "job_count": len(scheduler.get_jobs()),
    }
    return payload


@router.post("/score-vocab/reload")
def reload_score_vocab_runtime() -> Dict[str, Any]:
    """Reload YAML-backed score vocabulary without restarting PIM."""
    from app.domains.score import score_explain, score_rules, score_vocab

    snapshot = score_vocab.reload_score_vocab_from_disk()
    score_rules.refresh_score_vocab_bindings()
    score_explain.refresh_score_vocab_bindings()
    return {"status": "ok", "vocab": snapshot}


@router.get("/update-check")
async def get_update_check(include_prerelease: bool = False) -> Dict[str, Any]:
    """Check GitHub releases and report whether a newer PIM version exists."""
    from app.platform.runtime.update_check import check_for_updates

    return await check_for_updates(include_prerelease=include_prerelease)


@router.get("/upgrade")
def get_upgrade_status() -> Dict[str, Any]:
    """Return the latest UI-triggered upgrade status and log tail."""
    from app.platform.runtime.upgrade import get_upgrade_status as read_upgrade_status

    return read_upgrade_status()


@router.post("/upgrade")
def start_upgrade(target_version: str | None = None) -> Dict[str, Any]:
    """Start an upgrade runner and optionally verify its target version."""
    from app.platform.runtime.upgrade import start_upgrade as launch_upgrade

    return launch_upgrade(expected_version=target_version)


@router.get("/doctor")
async def get_system_doctor() -> Dict[str, Any]:
    """Perform a full system diagnostic audit."""
    from app.database import SessionLocal
    from app.domains.system.doctor import DoctorService

    def _run_audit() -> Dict[str, Any]:
        db = SessionLocal()
        try:
            return DoctorService(db).audit_all()
        finally:
            db.close()

    return await asyncio.to_thread(_run_audit)


@router.get("/support-bundle")
async def download_support_bundle() -> Response:
    """Generate a redacted diagnostic bundle for manual sharing."""
    from app.database import SessionLocal
    from app.domains.system.support_bundle import SupportBundleService

    def _build() -> tuple[str, bytes]:
        db = SessionLocal()
        try:
            return SupportBundleService(db).build_bundle_bytes()
        finally:
            db.close()

    filename, payload = await asyncio.to_thread(_build)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/search/rebuild")
async def rebuild_search_index() -> Dict[str, Any]:
    """Manually trigger a full rebuild of the search index."""
    from app.tasks.maintenance import rebuild_fts_index
    
    success = await rebuild_fts_index()
    if success:
        return {"status": "ok", "message": "Search index rebuild successful"}
    else:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Search index rebuild failed")


@router.get("/metrics/prometheus", response_class=PlainTextResponse)
def get_metrics_prometheus() -> str:
    """Expose Prometheus-compatible metrics for scraping."""
    scheduler_running = 1 if getattr(scheduler, "running", False) else 0
    scheduler_jobs = len(scheduler.get_jobs())
    metrics_text = request_metrics.prometheus_snapshot()
    metrics_text += task_queue_metrics.prometheus_snapshot()
    metrics_text += storage_metrics.prometheus_snapshot()
    metrics_text += reliability_metrics.prometheus_snapshot()
    metrics_text += (
        "# HELP pim_scheduler_running Whether the scheduler is running.\n"
        "# TYPE pim_scheduler_running gauge\n"
        f"pim_scheduler_running {scheduler_running}\n"
        "# HELP pim_scheduler_jobs Number of registered scheduler jobs.\n"
        "# TYPE pim_scheduler_jobs gauge\n"
        f"pim_scheduler_jobs {scheduler_jobs}\n"
    )
    return metrics_text
