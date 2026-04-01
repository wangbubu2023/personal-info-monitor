"""API routes package."""

from fastapi import APIRouter, Depends

from app.api import sources, contents, categories, keywords, digest, configs, dashboard, system
from app.auth import verify_api_key
from app.features import KEYWORD_MONITORING_ENABLED

api_router = APIRouter(dependencies=[Depends(verify_api_key)])

api_router.include_router(system.router, prefix="/system", tags=["system"])
api_router.include_router(sources.router, prefix="/sources", tags=["sources"])
api_router.include_router(contents.router, prefix="/contents", tags=["contents"])
api_router.include_router(categories.router, prefix="/categories", tags=["categories"])
if KEYWORD_MONITORING_ENABLED:
    api_router.include_router(keywords.router, prefix="/keywords", tags=["keywords"])
api_router.include_router(digest.router, prefix="/digest", tags=["digest"])
api_router.include_router(configs.router, prefix="/configs", tags=["configs"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
