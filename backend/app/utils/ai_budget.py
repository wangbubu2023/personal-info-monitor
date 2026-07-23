"""Persistent LLM token budget accounting.

The budget is intentionally conservative: callers reserve an estimated token
amount before an outbound LLM call. Usage is persisted in ``system_settings`` so
restarting the server cannot reset a daily or monthly cap.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.models.system_setting import SystemSetting
from app.platform.config.settings import get_settings
from app.utils.datetime import today_in_user_timezone
from app.platform.persistence.database import SessionLocal
from app.utils.logger import get_logger


logger = get_logger(__name__)

AI_USAGE_BUDGET_KEY = "ai_usage_budget"
_persistent_lock = threading.Lock()
_fallback_lock = threading.Lock()
_fallback_day: date | None = None
_fallback_month: str | None = None
_fallback_daily_total = 0
_fallback_monthly_total = 0


@dataclass(frozen=True)
class AiBudgetCaps:
    daily: int = 0
    monthly: int = 0

    @property
    def enabled(self) -> bool:
        return self.daily > 0 or self.monthly > 0


@dataclass(frozen=True)
class AiBudgetReservation:
    allowed: bool
    estimated_tokens: int
    daily_used: int
    monthly_used: int
    daily_cap: int
    monthly_cap: int
    reason: str = "ok"


@dataclass(frozen=True)
class AiBudgetStatus:
    available: bool
    daily_used: int
    monthly_used: int
    daily_cap: int
    monthly_cap: int
    reason: str = "ok"


def current_budget_caps() -> AiBudgetCaps:
    settings = get_settings()
    return AiBudgetCaps(
        daily=max(0, int(settings.ai_daily_token_budget or 0)),
        monthly=max(0, int(settings.ai_monthly_token_budget or 0)),
    )


def _usage_periods(today: date | None = None) -> tuple[str, str]:
    day = today or today_in_user_timezone()
    day_key = day.isoformat()
    month_key = f"{day.year:04d}-{day.month:02d}"
    return day_key, month_key


def _coerce_usage(raw: Any, *, today: date | None = None) -> dict[str, Any]:
    day_key, month_key = _usage_periods(today)
    usage = raw if isinstance(raw, dict) else {}
    if usage.get("day") != day_key:
        daily_used = 0
    else:
        daily_used = _coerce_non_negative_int(usage.get("daily_used_tokens"))
    if usage.get("month") != month_key:
        monthly_used = 0
    else:
        monthly_used = _coerce_non_negative_int(usage.get("monthly_used_tokens"))
    return {
        "day": day_key,
        "month": month_key,
        "daily_used_tokens": daily_used,
        "monthly_used_tokens": monthly_used,
    }


def _coerce_non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _clamp_estimate(estimated_tokens: int, caps: AiBudgetCaps) -> int:
    _ = caps
    return max(1, int(estimated_tokens or 0))


def reserve_ai_token_budget(estimated_tokens: int, *, caps: AiBudgetCaps | None = None) -> AiBudgetReservation:
    """Reserve estimated tokens and return whether an LLM call may proceed."""
    budget_caps = caps or current_budget_caps()
    if not budget_caps.enabled:
        return AiBudgetReservation(
            allowed=True,
            estimated_tokens=max(1, int(estimated_tokens or 0)),
            daily_used=0,
            monthly_used=0,
            daily_cap=budget_caps.daily,
            monthly_cap=budget_caps.monthly,
        )

    est = _clamp_estimate(estimated_tokens, budget_caps)
    try:
        return _reserve_persistent(est, budget_caps)
    except (RuntimeError, SQLAlchemyError) as exc:
        logger.warning("Persistent AI token budget unavailable; falling back to process-local accounting: %s", exc)
        return _reserve_fallback(est, budget_caps)


def get_ai_budget_status(*, caps: AiBudgetCaps | None = None) -> AiBudgetStatus:
    """Read budget availability without reserving or mutating usage."""

    budget_caps = caps or current_budget_caps()
    if not budget_caps.enabled:
        return AiBudgetStatus(True, 0, 0, budget_caps.daily, budget_caps.monthly)
    db = SessionLocal()
    try:
        row = db.query(SystemSetting).filter(SystemSetting.key == AI_USAGE_BUDGET_KEY).first()
        usage = _coerce_usage(row.value if row else {})
        daily_used = int(usage["daily_used_tokens"])
        monthly_used = int(usage["monthly_used_tokens"])
    except (RuntimeError, SQLAlchemyError):
        with _fallback_lock:
            daily_used = _fallback_daily_total
            monthly_used = _fallback_monthly_total
    finally:
        db.close()
    reason = _budget_denial_reason(daily_used + 1, monthly_used + 1, budget_caps)
    return AiBudgetStatus(
        available=reason is None,
        daily_used=daily_used,
        monthly_used=monthly_used,
        daily_cap=budget_caps.daily,
        monthly_cap=budget_caps.monthly,
        reason="budget_exhausted" if reason else "ok",
    )


def _reserve_persistent(est: int, caps: AiBudgetCaps) -> AiBudgetReservation:
    with _persistent_lock:
        db = SessionLocal()
        try:
            row = db.query(SystemSetting).filter(SystemSetting.key == AI_USAGE_BUDGET_KEY).first()
            usage = _coerce_usage(row.value if row else {})
            daily_after = int(usage["daily_used_tokens"]) + est
            monthly_after = int(usage["monthly_used_tokens"]) + est
            denied_reason = _budget_denial_reason(daily_after, monthly_after, caps)
            if denied_reason:
                return AiBudgetReservation(
                    allowed=False,
                    estimated_tokens=est,
                    daily_used=int(usage["daily_used_tokens"]),
                    monthly_used=int(usage["monthly_used_tokens"]),
                    daily_cap=caps.daily,
                    monthly_cap=caps.monthly,
                    reason=denied_reason,
                )

            usage["daily_used_tokens"] = daily_after
            usage["monthly_used_tokens"] = monthly_after
            if row is None:
                row = SystemSetting(key=AI_USAGE_BUDGET_KEY, value=usage)
                db.add(row)
            else:
                row.value = usage
            db.commit()
            return AiBudgetReservation(
                allowed=True,
                estimated_tokens=est,
                daily_used=daily_after,
                monthly_used=monthly_after,
                daily_cap=caps.daily,
                monthly_cap=caps.monthly,
            )
        finally:
            db.close()


def _reserve_fallback(est: int, caps: AiBudgetCaps) -> AiBudgetReservation:
    global _fallback_day, _fallback_month, _fallback_daily_total, _fallback_monthly_total

    day_key, month_key = _usage_periods()
    with _fallback_lock:
        if _fallback_day is None or _fallback_day.isoformat() != day_key:
            _fallback_day = date.fromisoformat(day_key)
            _fallback_daily_total = 0
        if _fallback_month != month_key:
            _fallback_month = month_key
            _fallback_monthly_total = 0

        daily_after = _fallback_daily_total + est
        monthly_after = _fallback_monthly_total + est
        denied_reason = _budget_denial_reason(daily_after, monthly_after, caps)
        if denied_reason:
            return AiBudgetReservation(
                allowed=False,
                estimated_tokens=est,
                daily_used=_fallback_daily_total,
                monthly_used=_fallback_monthly_total,
                daily_cap=caps.daily,
                monthly_cap=caps.monthly,
                reason=denied_reason,
            )

        _fallback_daily_total = daily_after
        _fallback_monthly_total = monthly_after
        return AiBudgetReservation(
            allowed=True,
            estimated_tokens=est,
            daily_used=daily_after,
            monthly_used=monthly_after,
            daily_cap=caps.daily,
            monthly_cap=caps.monthly,
        )


def _budget_denial_reason(daily_after: int, monthly_after: int, caps: AiBudgetCaps) -> str | None:
    if caps.daily > 0 and daily_after > caps.daily:
        return "daily_budget_exceeded"
    if caps.monthly > 0 and monthly_after > caps.monthly:
        return "monthly_budget_exceeded"
    return None


__all__ = [
    "AI_USAGE_BUDGET_KEY",
    "AiBudgetCaps",
    "AiBudgetReservation",
    "AiBudgetStatus",
    "current_budget_caps",
    "get_ai_budget_status",
    "reserve_ai_token_budget",
]
