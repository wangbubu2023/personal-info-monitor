"""API routes for browser session management."""

from __future__ import annotations

from pathlib import Path
from typing import Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models.auth_config import AuthConfig
from app.models.browser_session import BrowserSession, BrowserSessionStatus
from app.schemas.config import (
    BrowserSessionCreate,
    BrowserSessionOpenLoginRequest,
    BrowserSessionValidateRequest,
)
from app.utils.datetime import utcnow_naive
from app.utils.encryption import encrypt_data
from app.utils.logger import get_logger
from app.utils.url import host_matches, normalize_host
from app.api.configs_common import (
    bind_browser_session_to_sources,
    decrypt_auth_credentials,
    extract_auth_cookies_for_host,
    profiles_root,
    run_browser_bootstrap,
    run_browser_validation,
    serialize_browser_session,
    slugify_profile_name,
)

router = APIRouter()
logger = get_logger(__name__)


def _browser_error_message(action: str) -> str:
    return f"{action}失败，请查看服务端日志。"


@router.get("/browser-sessions")
async def list_browser_sessions(db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(BrowserSession).order_by(BrowserSession.site_host))
    sessions = result.scalars().all()
    return [serialize_browser_session(s) for s in sessions]


@router.post("/browser-sessions")
async def create_browser_session(
    session_data: BrowserSessionCreate,
    db: AsyncSession = Depends(get_async_db),
):
    site_host = normalize_host(session_data.site_url)
    if not site_host:
        raise HTTPException(status_code=422, detail="无效 site_url，无法解析 host")

    result = await db.execute(select(BrowserSession).filter(BrowserSession.site_host == site_host))
    existing = result.scalar_one_or_none()

    profile_name = slugify_profile_name(session_data.profile_name or site_host)
    user_data_dir = str(profiles_root() / profile_name)
    Path(user_data_dir).mkdir(parents=True, exist_ok=True)
    storage_state_path = str(Path(user_data_dir) / "storage_state.json")

    auth_config_id = session_data.auth_config_id
    if not auth_config_id:
        auth_query = await db.execute(select(AuthConfig).order_by(AuthConfig.updated_at.desc()))
        for cfg in auth_query.scalars().all():
            cfg_host = normalize_host(cfg.site_url)
            if host_matches(site_host, cfg_host):
                auth_config_id = cfg.id
                break

    if existing:
        existing.site_url = session_data.site_url
        existing.profile_name = profile_name
        existing.user_data_dir = user_data_dir
        existing.storage_state_path = storage_state_path
        existing.auth_config_id = auth_config_id
        session = existing
    else:
        session = BrowserSession(
            site_url=session_data.site_url,
            site_host=site_host,
            profile_name=profile_name,
            user_data_dir=user_data_dir,
            storage_state_path=storage_state_path,
            auth_config_id=auth_config_id,
            status=BrowserSessionStatus.NEEDS_LOGIN,
        )
        db.add(session)
        await db.flush()

    bound_sources = 0
    if session_data.auto_bind_sources:
        bound_sources = await bind_browser_session_to_sources(db, session)

    await db.commit()
    await db.refresh(session)
    payload = serialize_browser_session(session)
    payload["bound_sources"] = bound_sources
    return payload


@router.post("/browser-sessions/{session_id}/open-login")
async def open_browser_session_login(
    session_id: UUID,
    req: BrowserSessionOpenLoginRequest,
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(BrowserSession).filter(BrowserSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Browser session not found")

    auth_config = None
    if session.auth_config_id:
        auth_result = await db.execute(select(AuthConfig).filter(AuthConfig.id == session.auth_config_id))
        auth_config = auth_result.scalar_one_or_none()

    cookies = extract_auth_cookies_for_host(auth_config, session.site_host) if req.bootstrap_auth_cookies else {}

    try:
        boot = await run_browser_bootstrap(
            user_data_dir=session.user_data_dir,
            site_url=session.site_url,
            site_host=session.site_host,
            cookies=cookies,
            headless=req.headless,
            dwell_seconds=req.dwell_seconds,
        )
        session.status = BrowserSessionStatus.ACTIVE
        session.last_error = None
        session.last_validated_at = utcnow_naive()
        session.storage_state_path = str(Path(session.user_data_dir) / "storage_state.json")
        meta = dict(session.metadata_ or {})
        meta["last_bootstrap"] = {
            "at": utcnow_naive().isoformat() + "Z",
            "final_url": boot.get("final_url"),
            "title": boot.get("title"),
            "cookie_count": boot.get("cookie_count"),
            "headless": req.headless,
        }
        session.metadata_ = meta
        await db.commit()
        await db.refresh(session)
        payload = serialize_browser_session(session)
        payload["bootstrap"] = boot
        return payload
    except Exception as e:
        logger.exception("Browser bootstrap failed for session %s", session_id)
        if not req.headless:
            try:
                boot = await run_browser_bootstrap(
                    user_data_dir=session.user_data_dir,
                    site_url=session.site_url,
                    site_host=session.site_host,
                    cookies=cookies,
                    headless=True,
                    dwell_seconds=min(req.dwell_seconds, 8),
                )
                session.status = BrowserSessionStatus.NEEDS_LOGIN
                session.last_error = "可视化登录窗口打开失败，已退化为无头预热。"
                session.storage_state_path = str(Path(session.user_data_dir) / "storage_state.json")
                meta = dict(session.metadata_ or {})
                meta["last_bootstrap"] = {
                    "at": utcnow_naive().isoformat() + "Z",
                    "final_url": boot.get("final_url"),
                    "title": boot.get("title"),
                    "cookie_count": boot.get("cookie_count"),
                    "headless": True,
                    "fallback_reason": "headful_bootstrap_failed",
                }
                session.metadata_ = meta
                await db.commit()
                await db.refresh(session)
                payload = serialize_browser_session(session)
                payload["bootstrap"] = boot
                return payload
            except Exception as e2:
                logger.exception("Headless fallback bootstrap failed for session %s", session_id)
                session.status = BrowserSessionStatus.ERROR
                session.last_error = _browser_error_message("浏览器会话启动")
                await db.commit()
                raise HTTPException(status_code=500, detail=session.last_error) from e2

        session.status = BrowserSessionStatus.ERROR
        session.last_error = _browser_error_message("浏览器会话启动")
        await db.commit()
        raise HTTPException(status_code=500, detail=session.last_error) from e


@router.post("/browser-sessions/{session_id}/validate")
async def validate_browser_session(
    session_id: UUID,
    req: BrowserSessionValidateRequest,
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(select(BrowserSession).filter(BrowserSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Browser session not found")

    try:
        validation = await run_browser_validation(
            user_data_dir=session.user_data_dir,
            site_url=session.site_url,
            test_url=req.test_url,
            wait_ms=req.wait_ms,
            min_article_paragraphs=req.min_article_paragraphs,
        )
    except Exception as e:
        logger.exception("Browser validation failed for session %s", session_id)
        session.status = BrowserSessionStatus.ERROR
        session.last_error = _browser_error_message("浏览器会话校验")
        session.last_validated_at = utcnow_naive()
        await db.commit()
        raise HTTPException(status_code=500, detail=session.last_error) from e

    session.status = validation["status"]
    session.last_error = None if session.status == BrowserSessionStatus.ACTIVE else validation.get("message")
    session.last_validated_at = utcnow_naive()
    session.storage_state_path = str(Path(session.user_data_dir) / "storage_state.json")
    meta = dict(session.metadata_ or {})
    meta["last_validation"] = {
        "at": utcnow_naive().isoformat() + "Z",
        "message": validation.get("message"),
        "final_url": validation.get("final_url"),
        "title": validation.get("title"),
        "cookie_count": validation.get("cookie_count"),
        "paragraph_count": validation.get("paragraph_count"),
    }
    session.metadata_ = meta

    if req.sync_cookies_to_auth_config and session.auth_config_id and session.status == BrowserSessionStatus.ACTIVE:
        auth_result = await db.execute(select(AuthConfig).filter(AuthConfig.id == session.auth_config_id))
        auth_config = auth_result.scalar_one_or_none()
        if auth_config:
            existing = decrypt_auth_credentials(auth_config)
            cookie_dict: Dict[str, str] = {}
            for item in validation.get("cookies") or []:
                name = str(item.get("name") or "").strip()
                value = item.get("value")
                domain = str(item.get("domain") or "").lstrip(".").lower()
                if not name or value is None:
                    continue
                if host_matches(session.site_host, domain):
                    cookie_dict[name] = str(value)
            if cookie_dict and len(cookie_dict) >= 3:
                existing["cookies"] = cookie_dict
                existing["cookie_mode"] = "manual"
                existing["cookie_updated_at"] = utcnow_naive().isoformat() + "Z"
                auth_config.credentials = encrypt_data(existing)
                auth_config.last_validated_at = utcnow_naive()

    await db.commit()
    await db.refresh(session)
    payload = serialize_browser_session(session)
    payload["validation"] = {
        "message": validation.get("message"),
        "paragraph_count": validation.get("paragraph_count"),
        "cookie_count": validation.get("cookie_count"),
        "final_url": validation.get("final_url"),
    }
    return payload
