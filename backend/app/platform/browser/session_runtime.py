"""Build the runtime dict for a persisted BrowserSession profile.

Given a source whose ``metadata_`` references a ``browser_session_id``, load
the underlying ``BrowserSession`` row, inspect on-disk artefacts (profile dir,
storage_state.json), and emit a ``dict`` describing whether the session is
ready to drive an authenticated headless fetch.

``auth_ready=True`` requires *all* of:

* ``status == active``
* profile directory present on disk
* validation cookies + paragraph counts > 0
* last validation < ``BROWSER_SESSION_AUTH_TTL_DAYS`` ago

``auth_warning`` is a human-readable explanation of why ``auth_ready`` is
``False`` (or which non-fatal issue was noticed, e.g. missing storage_state).
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from uuid import UUID

from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger

logger = get_logger(__name__)

BROWSER_SESSION_AUTH_TTL_DAYS = 7


def build_browser_session_runtime(db, source) -> dict | None:
    metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
    raw_id = metadata.get("browser_session_id")
    if not raw_id:
        return None

    try:
        session_id = UUID(str(raw_id))
    except (TypeError, ValueError) as exc:
        logger.debug(
            "Invalid browser_session_id for source %s: %s",
            getattr(source, "id", "unknown"),
            exc,
        )
        return None

    try:
        from app.models.browser_session import BrowserSession

        session = db.query(BrowserSession).filter(BrowserSession.id == session_id).first()
    except Exception as exc:  # noqa: BLE001 - ORM may raise SQLAlchemy errors of many types
        logger.debug("Failed to load browser session %s: %s", session_id, exc)
        return None
    if not session:
        return None

    session_meta = session.metadata_ if isinstance(session.metadata_, dict) else {}
    last_validation = (
        session_meta.get("last_validation")
        if isinstance(session_meta.get("last_validation"), dict)
        else {}
    )
    user_data_dir = str(session.user_data_dir or "").strip()
    storage_state_path = str(session.storage_state_path or "").strip()
    profile_exists = bool(user_data_dir and Path(user_data_dir).is_dir())
    storage_state_exists = bool(storage_state_path and Path(storage_state_path).is_file())
    status = session.status.value if hasattr(session.status, "value") else str(session.status)
    last_validated_at = session.last_validated_at
    validation_fresh = bool(
        last_validated_at
        and utcnow_naive() - last_validated_at <= timedelta(days=BROWSER_SESSION_AUTH_TTL_DAYS)
    )
    validation_cookie_count = int(last_validation.get("cookie_count") or 0)
    validation_paragraph_count = int(last_validation.get("paragraph_count") or 0)
    auth_ready = bool(
        str(status).lower() == "active"
        and profile_exists
        and validation_fresh
        and validation_cookie_count > 0
        and validation_paragraph_count > 0
    )

    auth_warning = None
    if str(status).lower() != "active":
        auth_warning = f"浏览器会话未激活（status={status}），需要重新登录/校验"
    elif not profile_exists:
        auth_warning = "浏览器会话 profile 目录不存在，需要重新登录"
    elif not last_validated_at:
        auth_warning = "浏览器会话尚未完成正文校验，需要重新登录或校验"
    elif not validation_fresh:
        auth_warning = f"浏览器会话正文校验已超过 {BROWSER_SESSION_AUTH_TTL_DAYS} 天，需要重新校验"
    elif validation_cookie_count <= 0:
        auth_warning = "浏览器会话校验未捕获站点 cookies，需要重新登录"
    elif validation_paragraph_count <= 0:
        auth_warning = "浏览器会话校验未确认可读取正文段落，需要重新校验"
    elif storage_state_path and not storage_state_exists:
        auth_warning = "浏览器会话 storage_state.json 不存在，将仅使用 Chrome profile"

    return {
        "id": str(session.id),
        "site_url": session.site_url,
        "site_host": session.site_host,
        "profile_name": session.profile_name,
        "user_data_dir": user_data_dir,
        "storage_state_path": storage_state_path,
        "status": status,
        "last_validated_at": last_validated_at,
        "profile_exists": profile_exists,
        "storage_state_exists": storage_state_exists,
        "validation_fresh": validation_fresh,
        "validation_cookie_count": validation_cookie_count,
        "validation_paragraph_count": validation_paragraph_count,
        "auth_ready": auth_ready,
        "auth_warning": auth_warning,
    }
