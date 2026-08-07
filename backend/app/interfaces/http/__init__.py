"""HTTP interfaces — FastAPI routers and shared request/response shims.

Phase 5 step 15 of the refactor relocated this package from ``app.api``
to ``app.interfaces.http`` so the outward-facing HTTP layer lives next
to other interface adapters (CLI, scheduler-driven cron entry points,
future webhooks). The legacy ``app.api`` namespace stays in place as a
re-export shim through Phase 7 — every public symbol exposed below
remains importable from either path while callers (``app.main``, tests,
external operator scripts) migrate one at a time.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.interfaces.http import (
    ai_governance,
    annotations,
    atoms,
    briefs,
    configs,
    connectors,
    identity,
    contents,
    dashboard,
    digest,
    events,
    keywords,
    paid_matrix,
    personal_monitor,
    reliability,
    score_lab,
    sources,
    site_rules,
    system,
    topics,
    webhooks,
)
from app.platform.auth import verify_api_key
from app.features import KEYWORD_MONITORING_ENABLED, atoms_product_enabled


def _require_atoms_product_surface() -> None:
    if not atoms_product_enabled():
        raise HTTPException(status_code=404, detail="Atoms product surface is not enabled")

api_router = APIRouter(dependencies=[Depends(verify_api_key)])

api_router.include_router(system.router, prefix="/system", tags=["system"])
api_router.include_router(annotations.router, prefix="/annotations", tags=["annotations"])
api_router.include_router(ai_governance.router, prefix="/ai", tags=["ai-governance"])
api_router.include_router(reliability.router, prefix="/system/reliability", tags=["reliability"])
api_router.include_router(sources.router, prefix="/sources", tags=["sources"])
api_router.include_router(contents.router, prefix="/contents", tags=["contents"])
if KEYWORD_MONITORING_ENABLED:
    api_router.include_router(keywords.router, prefix="/keywords", tags=["keywords"])
api_router.include_router(digest.router, prefix="/digest", tags=["digest"])
api_router.include_router(events.router, prefix="/events", tags=["events"])
api_router.include_router(personal_monitor.router, prefix="/personal-monitor", tags=["personal-monitor"])
api_router.include_router(configs.router, prefix="/configs", tags=["configs"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(
    atoms.router,
    prefix="/atoms",
    tags=["atoms"],
    dependencies=[Depends(_require_atoms_product_surface)],
)
api_router.include_router(
    atoms.relations_router,
    prefix="/atom-relations",
    tags=["atoms"],
    dependencies=[Depends(_require_atoms_product_surface)],
)
api_router.include_router(score_lab.router, prefix="/score-lab", tags=["score-lab"])
api_router.include_router(paid_matrix.router, prefix="/paid-matrix", tags=["paid-matrix"])
api_router.include_router(topics.router, prefix="/topics", tags=["topics"])
api_router.include_router(briefs.router, prefix="/briefs", tags=["briefs"])
api_router.include_router(site_rules.router, prefix="/site-rules", tags=["site-rules"])
api_router.include_router(connectors.router, prefix="/connectors", tags=["connectors"])
api_router.include_router(webhooks.router, prefix="/integrations/webhooks", tags=["webhooks"])
api_router.include_router(identity.router, prefix="/identity", tags=["identity"])
