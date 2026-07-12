"""Platform-level failure classification for infrastructure jobs.

Workers must not import a business domain merely to turn an exception into a
structured operational record.  This small adapter keeps that boundary clean;
when a domain exception already carries a classified ``failure`` payload, its
fields are preserved, while common infrastructure failures receive stable
fallback values.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
@dataclass(frozen=True)
class ClassifiedFailure:
    code: str
    severity: str
    retryable: bool
    message: str


def _carried_failure(exc: BaseException) -> ClassifiedFailure | None:
    failure = getattr(exc, "failure", None)
    if failure is None:
        return None
    code = getattr(getattr(failure, "code", None), "value", None) or getattr(failure, "code", None)
    message = str(getattr(failure, "message", None) or str(exc) or exc.__class__.__name__)
    if not code:
        return None
    return ClassifiedFailure(
        code=str(code),
        severity=str(getattr(failure, "severity", "error") or "error"),
        retryable=bool(getattr(failure, "retryable", False)),
        message=message[:500],
    )


def classify_exception(exc: BaseException) -> ClassifiedFailure:
    """Classify an infrastructure failure without importing a business domain."""
    carried = _carried_failure(exc)
    if carried is not None:
        return carried

    detail = str(exc or "").strip() or exc.__class__.__name__
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return ClassifiedFailure("timeout", "warning", True, "抓取超时")

    status = getattr(exc, "status", None)
    if isinstance(status, int):
        if status == 429:
            return ClassifiedFailure("http_429", "warning", True, "请求过于频繁，已被限流（HTTP 429）")
        if status == 403:
            return ClassifiedFailure("http_403", "error", False, "访问被拒绝（HTTP 403）")
        if 500 <= status <= 599:
            return ClassifiedFailure("http_5xx", "warning", True, "目标站点服务器错误（HTTP 5xx）")
        if status >= 400:
            return ClassifiedFailure("http_client_error", "error", False, "请求失败（HTTP 4xx）")

    retryable = isinstance(exc, (ConnectionError, OSError))
    return ClassifiedFailure(
        "connection_error" if retryable else "unknown",
        "warning" if retryable else "error",
        retryable,
        detail[:500],
    )


__all__ = ["ClassifiedFailure", "classify_exception"]
