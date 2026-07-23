"""Unified fetch failure taxonomy.

This module is the single source of truth for "why did a fetch fail?". It
turns the heterogeneous exceptions and HTTP statuses produced across the
collector / pipeline layers into a small, stable, machine-readable
:class:`FetchFailure` value so the rest of the system (pipeline status,
scheduler cooldown, UI diagnostics) can reason about failures instead of
re-parsing free-form ``last_error`` strings.

Design notes (see ``PIM 爬取能力增强计划`` §4):

- :class:`FetchFailureCode` enumerates the failure classes.
- :class:`FetchFailure` is an immutable DTO carrying retryability, severity,
  an optional cooldown hint, the originating HTTP status and free-form details.
- :func:`classify_exception` / :func:`classify_http_status` are the two
  entry points; both return a fully-populated :class:`FetchFailure`.
- :func:`to_warning_entry` adapts a failure to the legacy
  ``(code, severity, message)`` warning tuple consumed by ``CollectorStage``
  and ``coordinator._update_source_status`` so integration is incremental and
  backwards compatible.

Only the *classification* lives here. Retry execution and circuit-breaker
state are deliberately left to later phases; this keeps the taxonomy a pure,
heavily-tested function with no side effects.
"""

from __future__ import annotations

import asyncio
import socket
import ssl
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

import aiohttp

Severity = Literal["info", "warning", "error"]


class FetchFailureCode(str, Enum):
    """Stable machine identifiers for fetch failure classes."""

    TIMEOUT = "timeout"
    DNS_ERROR = "dns_error"
    TLS_ERROR = "tls_error"
    CONNECTION_ERROR = "connection_error"
    HTTP_403 = "http_403"
    HTTP_429 = "http_429"
    HTTP_5XX = "http_5xx"
    HTTP_CLIENT_ERROR = "http_client_error"
    REDIRECT_BLOCKED = "redirect_blocked"
    SSRF_BLOCKED = "ssrf_blocked"
    LOGIN_REQUIRED = "login_required"
    SESSION_EXPIRED = "session_expired"
    BOT_WALL = "bot_wall"
    CAPTCHA = "captcha"
    RSS_STALE = "rss_stale"
    RSS_PARSE_ERROR = "rss_parse_error"
    HTML_PARSE_EMPTY = "html_parse_empty"
    BODY_INCOMPLETE = "body_incomplete"
    SOURCE_NOT_FOUND = "source_not_found"
    FETCH_ALREADY_RUNNING = "fetch_already_running"
    SOURCE_DISABLED = "source_disabled"
    SOURCE_TYPE_DISABLED = "source_type_disabled"
    DOMAIN_RATE_LIMITED = "domain_rate_limited"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FetchFailure:
    """An immutable, classified description of a single fetch failure."""

    code: FetchFailureCode
    retryable: bool
    severity: Severity
    message: str
    http_status: int | None = None
    cooldown_seconds: int | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable form, suitable for ``Source.metadata_``."""
        payload: dict[str, Any] = {
            "code": self.code.value,
            "retryable": self.retryable,
            "severity": self.severity,
            "message": self.message,
        }
        if self.http_status is not None:
            payload["http_status"] = self.http_status
        if self.cooldown_seconds is not None:
            payload["cooldown_seconds"] = self.cooldown_seconds
        if self.details:
            payload["details"] = dict(self.details)
        return payload


class FetchFailureError(RuntimeError):
    """Exception wrapper for collectors that already classified a fetch failure."""

    def __init__(self, failure: FetchFailure):
        super().__init__(failure.message)
        self.failure = failure


# --- Per-code default policy ------------------------------------------------
# (retryable, severity, default_cooldown_seconds)
_POLICY: dict[FetchFailureCode, tuple[bool, Severity, int | None]] = {
    FetchFailureCode.TIMEOUT: (True, "warning", None),
    FetchFailureCode.DNS_ERROR: (True, "error", None),
    FetchFailureCode.TLS_ERROR: (False, "error", None),
    FetchFailureCode.CONNECTION_ERROR: (True, "warning", None),
    FetchFailureCode.HTTP_403: (False, "error", 3600),
    FetchFailureCode.HTTP_429: (True, "warning", 900),
    FetchFailureCode.HTTP_5XX: (True, "warning", 120),
    FetchFailureCode.HTTP_CLIENT_ERROR: (False, "error", None),
    FetchFailureCode.REDIRECT_BLOCKED: (False, "error", None),
    FetchFailureCode.SSRF_BLOCKED: (False, "error", None),
    FetchFailureCode.LOGIN_REQUIRED: (False, "error", None),
    FetchFailureCode.SESSION_EXPIRED: (False, "error", None),
    FetchFailureCode.BOT_WALL: (False, "error", 3600),
    FetchFailureCode.CAPTCHA: (False, "error", 3600),
    FetchFailureCode.RSS_STALE: (False, "info", None),
    FetchFailureCode.RSS_PARSE_ERROR: (False, "warning", None),
    FetchFailureCode.HTML_PARSE_EMPTY: (False, "warning", None),
    FetchFailureCode.BODY_INCOMPLETE: (False, "warning", None),
    FetchFailureCode.SOURCE_NOT_FOUND: (False, "error", None),
    FetchFailureCode.FETCH_ALREADY_RUNNING: (True, "warning", 60),
    FetchFailureCode.SOURCE_DISABLED: (False, "info", None),
    FetchFailureCode.SOURCE_TYPE_DISABLED: (False, "info", None),
    FetchFailureCode.DOMAIN_RATE_LIMITED: (True, "warning", 60),
    FetchFailureCode.UNKNOWN: (True, "error", None),
}

# UI-facing Chinese messages; the source list renders these verbatim, so they
# match the tone of the existing ``auth_warning_entry`` / ``fetch_failed`` text.
_DEFAULT_MESSAGES: dict[FetchFailureCode, str] = {
    FetchFailureCode.TIMEOUT: "抓取超时",
    FetchFailureCode.DNS_ERROR: "域名解析失败",
    FetchFailureCode.TLS_ERROR: "TLS/SSL 证书错误",
    FetchFailureCode.CONNECTION_ERROR: "网络连接失败",
    FetchFailureCode.HTTP_403: "访问被拒绝（HTTP 403）",
    FetchFailureCode.HTTP_429: "请求过于频繁，已被限流（HTTP 429）",
    FetchFailureCode.HTTP_5XX: "目标站点服务器错误（HTTP 5xx）",
    FetchFailureCode.HTTP_CLIENT_ERROR: "请求失败（HTTP 4xx）",
    FetchFailureCode.REDIRECT_BLOCKED: "重定向次数过多或被拦截",
    FetchFailureCode.SSRF_BLOCKED: "目标地址被安全策略拦截",
    FetchFailureCode.LOGIN_REQUIRED: "需要登录后才能访问",
    FetchFailureCode.SESSION_EXPIRED: "登录态已失效，请重新登录",
    FetchFailureCode.BOT_WALL: "触发反爬墙（bot wall）",
    FetchFailureCode.CAPTCHA: "遇到验证码/人机校验",
    FetchFailureCode.RSS_STALE: "RSS 长期无更新",
    FetchFailureCode.RSS_PARSE_ERROR: "RSS 解析失败",
    FetchFailureCode.HTML_PARSE_EMPTY: "HTML 解析后无有效内容",
    FetchFailureCode.BODY_INCOMPLETE: "正文抓取不完整",
    FetchFailureCode.SOURCE_NOT_FOUND: "来源不存在",
    FetchFailureCode.FETCH_ALREADY_RUNNING: "来源正在抓取",
    FetchFailureCode.SOURCE_DISABLED: "来源已停用",
    FetchFailureCode.SOURCE_TYPE_DISABLED: "来源类型已停用",
    FetchFailureCode.DOMAIN_RATE_LIMITED: "来源域名被限速",
    FetchFailureCode.UNKNOWN: "未知抓取失败",
}

_MAX_MESSAGE_CHARS = 500


def make_failure(
    code: FetchFailureCode,
    *,
    message: str | None = None,
    detail: str | None = None,
    http_status: int | None = None,
    retryable: bool | None = None,
    severity: Severity | None = None,
    cooldown_seconds: int | None = None,
    details: dict[str, Any] | None = None,
) -> FetchFailure:
    """Build a :class:`FetchFailure`, filling unset fields from the policy table.

    ``message`` overrides the default localized text outright; ``detail`` is
    appended to the default message in parentheses (handy for surfacing the
    raw exception text without rewriting the human-readable label).
    """
    policy_retryable, policy_severity, policy_cooldown = _POLICY[code]
    base_message = message if message is not None else _DEFAULT_MESSAGES[code]
    if detail:
        detail = str(detail).strip()
        if detail and detail not in base_message:
            base_message = f"{base_message}（{detail}）"
    return FetchFailure(
        code=code,
        retryable=policy_retryable if retryable is None else retryable,
        severity=policy_severity if severity is None else severity,
        message=base_message[:_MAX_MESSAGE_CHARS],
        http_status=http_status,
        cooldown_seconds=policy_cooldown if cooldown_seconds is None else cooldown_seconds,
        details=dict(details or {}),
    )


def classify_http_status(
    status: int,
    *,
    retry_after: int | None = None,
    detail: str | None = None,
) -> FetchFailure | None:
    """Classify an HTTP status code into a :class:`FetchFailure`.

    Returns ``None`` for non-error statuses (< 400) so callers can use it as a
    simple "is this status a failure?" gate. ``retry_after`` (seconds) overrides
    the default 429 cooldown.
    """
    if status < 400:
        return None
    if status == 401:
        return make_failure(FetchFailureCode.LOGIN_REQUIRED, http_status=status, detail=detail)
    if status == 403:
        return make_failure(FetchFailureCode.HTTP_403, http_status=status, detail=detail)
    if status == 429:
        cooldown = retry_after if (retry_after and retry_after > 0) else None
        return make_failure(
            FetchFailureCode.HTTP_429,
            http_status=status,
            cooldown_seconds=cooldown,
            detail=detail,
        )
    if 500 <= status <= 599:
        return make_failure(FetchFailureCode.HTTP_5XX, http_status=status, detail=detail)
    return make_failure(FetchFailureCode.HTTP_CLIENT_ERROR, http_status=status, detail=detail)


# SSRF guard (app.platform.security.ssrf) raises ValueError with these markers.
_SSRF_VALUE_ERROR_MARKERS = (
    "unsupported scheme",
    "missing hostname",
    "localhost is not allowed",
    "private address is not allowed",
    "resolved to private address",
    "cookie host mismatch",
)


def _classify_value_error(exc: ValueError) -> FetchFailure:
    text = str(exc or "").strip()
    lowered = text.lower()
    if "redirect limit exceeded" in lowered:
        return make_failure(FetchFailureCode.REDIRECT_BLOCKED, detail=text)
    if "hostname did not resolve" in lowered:
        return make_failure(FetchFailureCode.DNS_ERROR, detail=text)
    if any(marker in lowered for marker in _SSRF_VALUE_ERROR_MARKERS):
        return make_failure(FetchFailureCode.SSRF_BLOCKED, detail=text)
    return make_failure(FetchFailureCode.UNKNOWN, detail=text or "ValueError")


def _is_dns_error(exc: BaseException) -> bool:
    dns_error_cls = getattr(aiohttp, "ClientConnectorDNSError", None)
    if dns_error_cls is not None and isinstance(exc, dns_error_cls):
        return True
    if isinstance(exc, socket.gaierror):
        return True
    os_error = getattr(exc, "os_error", None)
    return isinstance(os_error, socket.gaierror)


def _is_tls_error(exc: BaseException) -> bool:
    if isinstance(exc, ssl.SSLError):
        return True
    for attr in ("ClientConnectorCertificateError", "ClientConnectorSSLError", "ClientSSLError"):
        cls = getattr(aiohttp, attr, None)
        if cls is not None and isinstance(exc, cls):
            return True
    return isinstance(getattr(exc, "os_error", None), ssl.SSLError)


def classify_exception(exc: BaseException) -> FetchFailure:
    """Classify an arbitrary fetch exception into a :class:`FetchFailure`."""
    if isinstance(exc, FetchFailureError):
        return exc.failure

    detail = str(exc or "").strip() or exc.__class__.__name__

    if isinstance(exc, aiohttp.ClientResponseError):
        retry_after = _parse_retry_after(getattr(exc, "headers", None))
        classified = classify_http_status(
            int(getattr(exc, "status", 0) or 0),
            retry_after=retry_after,
            detail=detail,
        )
        if classified is not None:
            return classified

    # Timeouts (asyncio.TimeoutError aliases builtins.TimeoutError on 3.11+).
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or isinstance(
        exc, getattr(aiohttp, "ServerTimeoutError", ())
    ):
        return make_failure(FetchFailureCode.TIMEOUT, detail=detail)

    if _is_tls_error(exc):
        return make_failure(FetchFailureCode.TLS_ERROR, detail=detail)

    if _is_dns_error(exc):
        return make_failure(FetchFailureCode.DNS_ERROR, detail=detail)

    if isinstance(exc, (aiohttp.ClientConnectionError, ConnectionError)):
        return make_failure(FetchFailureCode.CONNECTION_ERROR, detail=detail)

    if isinstance(exc, ValueError):
        return _classify_value_error(exc)

    if isinstance(exc, aiohttp.ClientError):
        return make_failure(FetchFailureCode.CONNECTION_ERROR, detail=detail)

    return make_failure(FetchFailureCode.UNKNOWN, detail=detail)


def _parse_retry_after(headers: Any) -> int | None:
    """Best-effort parse of a ``Retry-After`` header value (seconds only)."""
    if not headers:
        return None
    try:
        raw = headers.get("Retry-After") or headers.get("retry-after")
    except (AttributeError, TypeError):
        return None
    if not raw:
        return None
    try:
        seconds = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def to_warning_entry(failure: FetchFailure) -> tuple[str, str, str]:
    """Adapt a :class:`FetchFailure` to the legacy ``(code, severity, message)`` tuple.

    This is the bridge into ``CollectorStage`` / ``coordinator`` which still
    speak the three-tuple warning protocol.
    """
    return (failure.code.value, failure.severity, failure.message[:_MAX_MESSAGE_CHARS])


__all__ = [
    "FetchFailureCode",
    "FetchFailure",
    "FetchFailureError",
    "Severity",
    "make_failure",
    "classify_exception",
    "classify_http_status",
    "to_warning_entry",
]
