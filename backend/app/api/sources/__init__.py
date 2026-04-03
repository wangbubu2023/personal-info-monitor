# backend/app/api/sources/__init__.py
"""Sources API package — combines all sub-routers into one router.

Import: from app.api.sources import router
"""

from fastapi import APIRouter

from app.services.system_settings import get_system_settings_async  # noqa: F401 – kept for test monkeypatching
from ._helpers import (  # noqa: F401 – re-exported for backward-compat test monkeypatching
    _probe_urls,
    _invalidate_source_cache,
    _ensure_source_quota,
    serialize_source,
)

from .query import router as query_router, list_sources, export_sources, get_source
from .mutation import router as mutation_router, create_source, update_source, delete_source
from .probe import router as probe_router
from .fetch_import import router as fetch_import_router

router = APIRouter()

# Order matters: fixed-path routes before parameterised /{source_id}.
# Routes with empty-string paths are registered via add_api_route to avoid
# the FastAPI restriction that forbids empty prefix + empty path in include_router.
router.include_router(probe_router)          # /probe, /probe-all, /{id}/probe
router.include_router(fetch_import_router)   # /bulk-import, /fetch-all, /{id}/fetch

# query sub-router: register "" routes directly, delegate the rest via include_router
router.add_api_route("", list_sources, methods=["GET"])
router.add_api_route("/export", export_sources, methods=["GET"])
router.add_api_route("/{source_id}", get_source, methods=["GET"])

# mutation sub-router: register "" route directly, delegate the rest via include_router
router.add_api_route("", create_source, methods=["POST"])
router.add_api_route("/{source_id}", update_source, methods=["PATCH"])
router.add_api_route("/{source_id}", delete_source, methods=["DELETE"])
