"""API routes for browser session management."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.features import PlaywrightDisabledError
from app.models.auth_config import AuthConfig
from app.models.browser_session import BrowserSession, BrowserSessionMode, BrowserSessionStatus
from app.schemas.config import (
    BrowserSessionCreate,
    BrowserSessionOpenLoginRequest,
    BrowserSessionValidateRequest,
)
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger
from app.utils.url import host_matches, normalize_host
from app.interfaces.http.configs_common_cookies import extract_auth_cookies_for_host
from app.domains.fetch.auth import (
    bind_browser_session_to_sources,
    ensure_x_shared_auth_config,
    serialize_browser_session,
    sync_cookies_to_auth_config,
)
from app.platform.browser import (
    HeadfulBrowserUnavailableError,
    is_x_host,
    profiles_root,
    run_browser_bootstrap,
    run_browser_validation,
    slugify_profile_name,
)

router = APIRouter()
logger = get_logger(__name__)


def _browser_error_message(action: str) -> str:
    return f"{action}失败，请查看服务端日志。"


_X_HEADLESS_LOGIN_DETAIL = (
    "X 登录必须使用可视化浏览器：需要人工完成 CAPTCHA/2FA 后才能捕获 auth_token/ct0。"
    "请在有 DISPLAY 的桌面环境运行，或在 VPS 上用 xvfb-run/系统级 Xvfb 启动 PIM 服务后重试。"
)


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

    # For x.com/twitter.com, make sure there's always a shared X auth_config
    # to act as the landing spot for synced cookies — otherwise the new
    # browser-session-driven X login has nowhere to write ``auth_token`` /
    # ``ct0`` and the existing X collector can't pick them up.
    if not auth_config_id and is_x_host(site_host):
        x_cfg = await ensure_x_shared_auth_config(db, session_data.site_url, site_host)
        if x_cfg:
            auth_config_id = x_cfg.id

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
            session_mode=BrowserSessionMode.PERSISTENT_PROFILE.value,
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

    # If this is an X session with no auth_config yet (e.g. the original
    # shared row was deleted and the unlink cleared ``session.auth_config_id``),
    # materialize one now so the sync-cookies-after-login path has a place to
    # land the fresh ``auth_token`` / ``ct0``. Without this, every X login
    # looks "successful" but yields no usable credentials downstream.
    if not auth_config and is_x_host(session.site_host):
        x_cfg = await ensure_x_shared_auth_config(db, session.site_url, session.site_host)
        if x_cfg:
            session.auth_config_id = x_cfg.id
            auth_config = x_cfg

    if is_x_host(session.site_host) and req.headless:
        session.status = BrowserSessionStatus.NEEDS_LOGIN
        session.last_error = _X_HEADLESS_LOGIN_DETAIL
        await db.commit()
        raise HTTPException(status_code=422, detail=_X_HEADLESS_LOGIN_DETAIL)

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

        # Sync the fresh cookies straight into the linked auth_config so the
        # regular pipeline (website + X collectors) can consume them without
        # a separate "validate" click. Particularly important for X where
        # the collector only reads from auth_config.credentials.
        cookies_synced = False
        if auth_config and session.auth_config_id and req.sync_cookies_to_auth_config:
            cookies_synced = sync_cookies_to_auth_config(
                auth_config,
                boot.get("cookies"),
                session.site_host,
            )
        payload_extra_sync = cookies_synced

        await db.commit()
        await db.refresh(session)
        payload = serialize_browser_session(session)
        # Never leak raw cookies back to the frontend — drop them before
        # returning.
        boot_public = {k: v for k, v in boot.items() if k != "cookies"}
        payload["bootstrap"] = boot_public
        payload["cookies_synced"] = payload_extra_sync
        return payload
    except PlaywrightDisabledError as exc:
        logger.warning("Browser bootstrap rejected: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="浏览器自动化已被管理员禁用（PIM_FEATURE_PLAYWRIGHT=false）。",
        ) from exc
    except HeadfulBrowserUnavailableError as exc:
        logger.warning("Headful browser bootstrap unavailable for session %s: %s", session_id, exc)
        session.status = BrowserSessionStatus.ERROR
        session.last_error = str(exc)
        await db.commit()
        raise HTTPException(status_code=503, detail=session.last_error) from exc
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
                payload["bootstrap"] = {k: v for k, v in boot.items() if k != "cookies"}
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


@router.delete("/browser-sessions/{session_id}", status_code=204)
async def delete_browser_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """Remove a persistent browser session.

    The on-disk user-data directory is intentionally kept so that a user can
    recover the login state by re-creating a session with the same site_url.
    If they want to wipe local state, they can delete the ``user_data_dir``
    path manually (returned by the list endpoint).
    """
    result = await db.execute(select(BrowserSession).filter(BrowserSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Browser session not found")
    logger.info(
        "Deleting browser session %s (host=%s, user_data_dir=%s left on disk)",
        session_id,
        session.site_host,
        session.user_data_dir,
    )
    await db.delete(session)
    await db.commit()
    return None


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

    # Same self-heal as open-login: make sure X sessions always have a
    # shared auth_config to sync into, otherwise the validate path silently
    # drops the freshly-captured cookies.
    if not session.auth_config_id and is_x_host(session.site_host):
        x_cfg = await ensure_x_shared_auth_config(db, session.site_url, session.site_host)
        if x_cfg:
            session.auth_config_id = x_cfg.id

    try:
        validation = await run_browser_validation(
            user_data_dir=session.user_data_dir,
            site_url=session.site_url,
            test_url=req.test_url,
            wait_ms=req.wait_ms,
            min_article_paragraphs=req.min_article_paragraphs,
            storage_state_path=session.storage_state_path,
            session_mode=str(session.session_mode or "persistent_profile"),
        )
    except PlaywrightDisabledError as exc:
        logger.warning("Browser validation rejected: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="浏览器自动化已被管理员禁用（PIM_FEATURE_PLAYWRIGHT=false）。",
        ) from exc
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
    if str(session.session_mode or "") == BrowserSessionMode.PERSISTENT_PROFILE.value and session.user_data_dir:
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
        # Paywall sites (NYT etc.) carry a large cookie jar, so require at
        # least 3 site-scoped cookies before overwriting the stored
        # credentials. X only needs auth_token + ct0 to function, so it
        # settles for just two matching cookies.
        x_sync = is_x_host(session.site_host)
        sync_cookies_to_auth_config(
            auth_config,
            validation.get("cookies"),
            session.site_host,
            min_cookies=2 if x_sync else 3,
        )

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


@router.post("/browser-sessions/{session_id}/bind-sources")
async def rebind_browser_session_sources(
    session_id: UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """Bind every matching monitoring source to this browser session.

    Browser sessions are naturally one-to-many (a single x.com login covers
    every X feed; a single nytimes.com login covers every NYT RSS/article
    source). This endpoint exposes
    :func:`bind_browser_session_to_sources` as an explicit user action so
    users can rebind after adding new sources or after losing the link via
    legacy cleanup, without having to re-create the session. For X sessions
    missing an ``auth_config_id`` (e.g. the shared row was deleted earlier),
    we also self-heal the link before binding, otherwise the X branch of the
    binder has nothing to point sources at.
    """
    result = await db.execute(select(BrowserSession).filter(BrowserSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Browser session not found")

    if not session.auth_config_id and is_x_host(session.site_host):
        x_cfg = await ensure_x_shared_auth_config(db, session.site_url, session.site_host)
        if x_cfg:
            session.auth_config_id = x_cfg.id

    bound = await bind_browser_session_to_sources(db, session)
    await db.commit()
    await db.refresh(session)
    payload = serialize_browser_session(session)
    payload["bound_sources"] = bound
    return payload
