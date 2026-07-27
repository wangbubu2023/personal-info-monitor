"""HTTP interfaces — FastAPI routers and shared request/response shims.

Phase 5 step 15 of the refactor relocated this package from ``app.api``
to ``app.interfaces.http`` so the outward-facing HTTP layer lives next
to other interface adapters (CLI, scheduler-driven cron entry points,
future webhooks). The legacy ``app.api`` namespace stays in place as a
re-export shim through Phase 7 — every public symbol exposed below
remains importable from either path while callers (``app.main``, tests,
external operator scripts) migrate one at a time.
"""

from fastapi import APIRouter, Depends

from app.interfaces.http import (
    ai_governance,
    briefs,
    configs,
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
    system,
    topics,
)
from app.platform.auth import verify_api_key
from app.features import ATOMS_PRODUCT_ENABLED, KEYWORD_MONITORING_ENABLED

if ATOMS_PRODUCT_ENABLED:
    from app.interfaces.http import atoms

api_router = APIRouter(dependencies=[Depends(verify_api_key)])

api_router.include_router(system.router, prefix="/system", tags=["system"])
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
if ATOMS_PRODUCT_ENABLED:
    api_router.include_router(atoms.router, prefix="/atoms", tags=["atoms"])
    api_router.include_router(atoms.relations_router, prefix="/atom-relations", tags=["atoms"])
api_router.include_router(score_lab.router, prefix="/score-lab", tags=["score-lab"])
api_router.include_router(paid_matrix.router, prefix="/paid-matrix", tags=["paid-matrix"])
api_router.include_router(topics.router, prefix="/topics", tags=["topics"])
api_router.include_router(briefs.router, prefix="/briefs", tags=["briefs"])
