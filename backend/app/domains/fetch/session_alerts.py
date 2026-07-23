"""Session-health warnings and operator alerts for fetch sources."""

from __future__ import annotations

import asyncio
import html
from datetime import datetime, timedelta
from typing import Any

from app.domains.fetch.session_health import (
    record_session_health_alert,
    session_health_alert_metadata,
    session_health_metadata,
)
from app.platform.notifications.smtp import send_email
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger

logger = get_logger(__name__)

_ALERT_DEDUPE_HOURS = 24


def _session_health(source) -> dict[str, Any]:
    return session_health_metadata(source)


def session_health_warning_entry(source) -> tuple[str, str, str] | None:
    """Convert ``metadata.session_health`` into the fetch warning channel."""
    health = _session_health(source)
    status = str(health.get("status") or "").strip().lower()
    if status not in {"warning", "error"}:
        return None
    reason = str(health.get("reason") or "unknown").strip() or "unknown"
    action = str(health.get("suggested_action") or "relogin").strip() or "relogin"
    code = "session_expired" if reason == "expired" else f"session_{reason}"
    severity = "error" if status == "error" else "warning"
    return (code, severity, f"会话健康异常：{reason}，建议操作：{action}")


def _parse_iso(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def stamp_session_health_alert(source, *, now: datetime | None = None) -> bool:
    """Return True and stamp metadata when a new session alert should be sent."""
    health = _session_health(source)
    if str(health.get("status") or "").strip().lower() != "error":
        return False
    reason = str(health.get("reason") or "unknown").strip() or "unknown"
    now = now or utcnow_naive()
    previous = session_health_alert_metadata(source)
    previous_sent = _parse_iso(str(previous.get("sent_at") or ""))
    if (
        previous.get("reason") == reason
        and previous_sent is not None
        and previous_sent >= now - timedelta(hours=_ALERT_DEDUPE_HOURS)
    ):
        return False
    record_session_health_alert(source, reason=reason, sent_at=now)
    return True


def _build_session_alert_payload(source_id: str) -> list[tuple[str, str, str]]:
    from app.config import get_settings
    from app.database import SessionLocal
    from app.models import EmailSchedule, Source

    settings = get_settings()
    db = SessionLocal()
    try:
        source = db.query(Source).filter(Source.id == source_id).first()
        if source is None:
            return []
        health = _session_health(source)
        if str(health.get("status") or "").strip().lower() != "error":
            return []

        recipients: set[str] = set()
        schedules = db.query(EmailSchedule).filter(EmailSchedule.enabled == True).all()
        for schedule in schedules:
            for item in schedule.recipients or []:
                email = str(item or "").strip()
                if email:
                    recipients.add(email)
        if not recipients and settings.smtp_user:
            recipients.add(settings.smtp_user)
        if not recipients:
            return []

        reason = html.escape(str(health.get("reason") or "unknown"))
        action = html.escape(str(health.get("suggested_action") or "relogin"))
        source_name = html.escape(str(source.name or source.url or source.id))
        source_url = html.escape(str(source.url or ""), quote=True)
        validated_at = html.escape(str(health.get("validated_at") or ""))
        details = health.get("details") if isinstance(health.get("details"), dict) else {}
        final_url = html.escape(str(details.get("final_url") or ""), quote=True)
        subject = f"PIM session alert: {source.name or source.id} ({reason})"
        body = (
            "<!DOCTYPE html><html><body style=\"font-family:sans-serif;padding:20px;\">"
            "<h2>PIM 会话告警</h2>"
            f"<p>信源 <strong>{source_name}</strong> 的登录会话异常。</p>"
            "<table style=\"border-collapse:collapse;font-size:14px;\">"
            f"<tr><td style=\"padding:4px 10px;color:#64748b;\">Reason</td><td>{reason}</td></tr>"
            f"<tr><td style=\"padding:4px 10px;color:#64748b;\">Action</td><td>{action}</td></tr>"
            f"<tr><td style=\"padding:4px 10px;color:#64748b;\">Source</td><td>{source_url}</td></tr>"
            f"<tr><td style=\"padding:4px 10px;color:#64748b;\">Final URL</td><td>{final_url}</td></tr>"
            f"<tr><td style=\"padding:4px 10px;color:#64748b;\">Validated</td><td>{validated_at}</td></tr>"
            "</table>"
            "<p style=\"color:#64748b;font-size:12px;\">"
            "请重新采集/导入会话，或按建议操作切换抓取策略。"
            "</p></body></html>"
        )
        return [(recipient, subject, body) for recipient in sorted(recipients)]
    finally:
        db.close()


async def send_session_health_alert(source_id: str) -> bool:
    """Send a deduped session-health alert for a source."""
    tasks = await asyncio.to_thread(_build_session_alert_payload, source_id)
    sent_any = False
    for recipient, subject, body in tasks:
        if await send_email(
            recipient,
            subject,
            body,
            idempotency_key=f"session-alert:{source_id}:{recipient}:{subject}",
            aggregate_type="source",
            aggregate_id=source_id,
        ):
            sent_any = True
    return sent_any


__all__ = [
    "send_session_health_alert",
    "session_health_warning_entry",
    "stamp_session_health_alert",
]
