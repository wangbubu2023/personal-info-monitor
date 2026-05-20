"""Aggregated configuration routes."""

from fastapi import APIRouter

from app.interfaces.http.configs_api_auth import router as api_auth_router
from app.interfaces.http.configs_browser import router as browser_router
from app.interfaces.http.configs_system import router as system_router

router = APIRouter()
router.include_router(api_auth_router)
router.include_router(browser_router)
router.include_router(system_router)
