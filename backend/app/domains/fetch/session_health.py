"""Browser-session health classification.

Login-backed fetches fail in ways that look identical to "no new content"
unless we inspect *why* (plan §10). Given the result of visiting a
``check_url`` with the current browser/cookie session — the final URL, the page
HTML, and which key selectors were expected — this module produces a structured
:class:`SessionHealth` verdict and a concrete suggested action (relogin, switch
to RSS-only, disable Playwright, retry later) the scheduler/UI can act on.

Pure function: HTML + URLs in, verdict out. The browser driving lives in the
validate API; this is the part worth unit-testing exhaustively.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

SessionStatus = str  # "ok" | "warning" | "error"
SessionReason = str  # "ok" | "login_required" | "captcha" | "bot_wall" | "expired" | "selector_missing"
SuggestedAction = str  # "relogin" | "switch_rss_only" | "disable_playwright" | "retry_later" | "none"

_LOGIN_URL_MARKERS = ("/login", "/signin", "/sign-in", "/auth", "/account/login", "/sessions/new")
_LOGIN_TEXT_MARKERS = (
    "sign in", "log in", "please log in", "please sign in", "create an account",
    "登录", "请登录", "登录后", "注册账号", "立即登录",
)
_CAPTCHA_MARKERS = (
    "captcha", "i'm not a robot", "verify you are human", "are you a robot",
    "人机验证", "安全验证", "请完成验证",
)
_BOT_WALL_MARKERS = (
    "access denied", "you have been blocked", "request blocked", "attention required",
    "checking your browser", "enable javascript and cookies to continue", "cloudflare",
    "访问被拒绝", "访问受限",
)


@dataclass(frozen=True)
class SessionHealth:
    status: SessionStatus
    reason: SessionReason
    suggested_action: SuggestedAction
    validated_at: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "reason": self.reason,
            "suggested_action": self.suggested_action,
        }
        if self.validated_at:
            payload["validated_at"] = self.validated_at
        if self.details:
            payload["details"] = dict(self.details)
        return payload


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _metadata_mapping(source) -> Mapping[str, Any]:
    metadata = getattr(source, "metadata_", None)
    return metadata if isinstance(metadata, Mapping) else {}


def _datetime_to_iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat() + "Z"
    return None


def record_session_health(source, health: SessionHealth | Mapping[str, Any]) -> dict[str, Any]:
    """Stamp latest session health onto structured columns and metadata."""
    payload = health.to_dict() if isinstance(health, SessionHealth) else dict(health)
    details = payload.get("details") if isinstance(payload.get("details"), Mapping) else {}
    validated_at = _parse_iso_datetime(payload.get("validated_at"))

    if hasattr(source, "session_health_status"):
        source.session_health_status = str(payload.get("status") or "")
        source.session_health_reason = str(payload.get("reason") or "")
        source.session_health_suggested_action = str(payload.get("suggested_action") or "")
        source.session_health_validated_at = validated_at
        source.session_health_details = dict(details)

    metadata = dict(getattr(source, "metadata_", None) or {})
    metadata["session_health"] = payload
    source.metadata_ = metadata
    return payload


def session_health_metadata(source) -> dict[str, Any]:
    """Return latest session health, preferring structured columns."""
    status = getattr(source, "session_health_status", None)
    if status:
        payload: dict[str, Any] = {
            "status": status,
            "reason": getattr(source, "session_health_reason", None),
            "suggested_action": getattr(source, "session_health_suggested_action", None),
        }
        validated_at = _datetime_to_iso(getattr(source, "session_health_validated_at", None))
        if validated_at:
            payload["validated_at"] = validated_at
        details = getattr(source, "session_health_details", None)
        if isinstance(details, Mapping) and details:
            payload["details"] = dict(details)
        return payload

    value = _metadata_mapping(source).get("session_health")
    return dict(value) if isinstance(value, Mapping) else {}


def record_session_health_alert(source, *, reason: str, sent_at: datetime) -> dict[str, Any]:
    """Stamp latest session-health alert dedupe state onto columns and metadata."""
    payload = {
        "reason": str(reason or "unknown"),
        "sent_at": sent_at.isoformat() + "Z",
    }
    if hasattr(source, "session_health_alert_reason"):
        source.session_health_alert_reason = payload["reason"]
        source.session_health_alert_sent_at = sent_at

    metadata = dict(getattr(source, "metadata_", None) or {})
    metadata["session_health_alert"] = payload
    source.metadata_ = metadata
    return payload


def session_health_alert_metadata(source) -> dict[str, Any]:
    """Return latest session-health alert stamp, preferring structured columns."""
    reason = getattr(source, "session_health_alert_reason", None)
    if reason:
        payload: dict[str, Any] = {"reason": reason}
        sent_at = _datetime_to_iso(getattr(source, "session_health_alert_sent_at", None))
        if sent_at:
            payload["sent_at"] = sent_at
        return payload

    value = _metadata_mapping(source).get("session_health_alert")
    return dict(value) if isinstance(value, Mapping) else {}


def _path_q(url: str) -> str:
    parsed = urlparse(url or "")
    return f"{parsed.path}?{parsed.query}".lower()


def _is_login_url(url: str) -> bool:
    blob = _path_q(url)
    return any(marker in blob for marker in _LOGIN_URL_MARKERS)


def _contains_any(text: str, markers: Sequence[str]) -> bool:
    return any(m in text for m in markers)


def classify_session_health(
    *,
    check_url: str,
    final_url: str | None = None,
    html: str | None = None,
    required_selectors_present: Sequence[bool] | None = None,
    cookie_count: int | None = None,
    validated_at: str | None = None,
) -> SessionHealth:
    """Classify session health from a validation visit.

    ``required_selectors_present`` is the per-selector presence result for the
    caller's configured key selectors (the browser side does the DOM query;
    this module only reasons about the booleans).
    """
    final_url = final_url or check_url
    text = (html or "").lower()
    details: dict[str, Any] = {"check_url": check_url, "final_url": final_url}
    if cookie_count is not None:
        details["cookie_count"] = cookie_count

    # 1. Redirected to a login page even though we didn't start on one.
    if _is_login_url(final_url) and not _is_login_url(check_url):
        return SessionHealth("error", "login_required", "relogin", validated_at, details)

    # 2. Bot wall — site actively blocking automation.
    if _contains_any(text, _BOT_WALL_MARKERS):
        return SessionHealth("error", "bot_wall", "switch_rss_only", validated_at, details)

    # 3. Captcha / human challenge.
    if _contains_any(text, _CAPTCHA_MARKERS):
        return SessionHealth("error", "captcha", "relogin", validated_at, details)

    # 4. In-page login prompt (cookies present but expired/insufficient).
    if html is not None and _contains_any(text, _LOGIN_TEXT_MARKERS) and len(text) < 4000:
        reason = "expired" if cookie_count else "login_required"
        return SessionHealth("error", reason, "relogin", validated_at, details)

    # 5. Page loaded but the expected content selectors are missing.
    if required_selectors_present is not None and len(required_selectors_present) > 0:
        if not any(required_selectors_present):
            return SessionHealth("warning", "selector_missing", "retry_later", validated_at, details)

    return SessionHealth("ok", "ok", "none", validated_at, details)


__all__ = [
    "SessionHealth",
    "classify_session_health",
    "record_session_health",
    "record_session_health_alert",
    "session_health_alert_metadata",
    "session_health_metadata",
]
