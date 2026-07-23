"""DoctorService daily digest email (nag-on-degraded).

The scheduler runs :func:`send_doctor_digest_email` once a day; the
job is a no-op when SMTP is not configured or ``DoctorService.audit_all``
returns ``overall_status == "ok"``. On warning / degraded / error we
render a structured HTML report and dispatch to every recipient that
has at least one enabled :class:`EmailSchedule`, falling back to
``SMTP_USER`` when no schedules are configured.

Phase 4 step 7 of the refactor extracted this from the legacy
``app.tasks.email_tasks`` module.
"""

from __future__ import annotations

import asyncio
import html
from datetime import datetime
from typing import Dict

from app.platform.notifications.smtp import send_email
from app.utils.datetime import today_in_user_timezone
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def send_doctor_digest_email() -> bool:
    """Send a daily DoctorService digest email on `degraded` / `error` status.

    Scheduled daily (see :mod:`app.scheduler`). The job is a no-op when SMTP
    is not configured or when all doctor checks pass — we don't send "all
    clear" emails to avoid alert fatigue on the operator mailbox. When any
    category is non-ok, we bundle the structured report into a plain HTML
    digest and send it to every recipient that has at least one enabled
    :class:`~app.models.EmailSchedule`, falling back to ``SMTP_USER`` when
    no schedules are configured.
    """
    from app.config import get_settings

    settings = get_settings()
    if not settings.smtp_user or not settings.smtp_password:
        logger.info("Skipping doctor digest: SMTP is not configured")
        return False

    def _build_report() -> tuple[dict, list[str]]:
        from app.database import SessionLocal
        from app.models import EmailSchedule
        from app.domains.system.doctor import DoctorService

        db = SessionLocal()
        try:
            report = DoctorService(db).audit_all()
            recipients: set[str] = set()
            schedules = db.query(EmailSchedule).filter(EmailSchedule.enabled == True).all()
            for schedule in schedules:
                for addr in schedule.recipients or []:
                    clean = str(addr or "").strip()
                    if clean:
                        recipients.add(clean)
            if not recipients and settings.smtp_user:
                recipients.add(settings.smtp_user)
            return report, sorted(recipients)
        finally:
            db.close()

    report, recipients = await asyncio.to_thread(_build_report)
    overall = str(report.get("overall_status") or "").lower()

    # Stay quiet on healthy days — the metric endpoint still exposes the raw
    # state for dashboards, and doctor emails are meant to nag, not narrate.
    if overall == "ok":
        logger.debug("Doctor digest: overall status OK, skipping email")
        return False
    if not recipients:
        logger.warning("Doctor digest: overall=%s but no recipients configured", overall)
        return False

    subject = f"PIM Doctor: {overall.upper()} ({today_in_user_timezone().isoformat()})"
    html_body = _render_doctor_digest_html(report)

    sent_any = False
    for recipient in recipients:
        if await send_email(
            recipient,
            subject,
            html_body,
            idempotency_key=f"doctor-digest:{recipient}:{subject}",
            aggregate_type="doctor_report",
            aggregate_id=subject,
        ):
            sent_any = True
    if sent_any:
        logger.info("Sent doctor digest (overall=%s) to %d recipient(s)", overall, len(recipients))
    return sent_any


def _render_doctor_digest_html(report: Dict) -> str:
    """Render the DoctorService audit payload as a self-contained HTML digest."""
    overall = str(report.get("overall_status") or "unknown")
    timestamp = str(report.get("timestamp") or datetime.now().isoformat())

    def _badge(status: str) -> str:
        color = {"ok": "#16a34a", "warning": "#d97706", "degraded": "#d97706", "error": "#dc2626"}.get(
            status.lower(), "#64748b"
        )
        return (
            f'<span style="display:inline-block;padding:2px 10px;border-radius:12px;'
            f'background:{color};color:#fff;font-size:12px;font-weight:600;'
            f'text-transform:uppercase;">{html.escape(status or "unknown")}</span>'
        )

    sections: list[str] = []
    for category in ("database", "environment", "workers", "collectors", "integrations"):
        data = report.get(category)
        if not isinstance(data, dict):
            continue
        rows: list[str] = []
        status = str(data.get("status") or "unknown")
        for key, value in data.items():
            if key == "status":
                continue
            if isinstance(value, (list, tuple)):
                safe_value = "<br>".join(html.escape(str(item)) for item in value)
            else:
                safe_value = html.escape(str(value))
            rows.append(
                f'<tr><td style="padding:4px 10px;color:#64748b;white-space:nowrap;">'
                f'{html.escape(str(key))}</td>'
                f'<td style="padding:4px 10px;color:#0f172a;">{safe_value}</td></tr>'
            )
        sections.append(
            '<section style="margin:18px 0;padding:14px 18px;border:1px solid #e2e8f0;border-radius:8px;">'
            f'<h3 style="margin:0 0 10px 0;font-size:15px;">'
            f'{html.escape(category.capitalize())} &nbsp;{_badge(status)}</h3>'
            f'<table style="width:100%;border-collapse:collapse;font-size:13px;">'
            + "".join(rows)
            + "</table></section>"
        )

    return (
        "<!DOCTYPE html>"
        '<html><body style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;'
        'background:#f8fafc;color:#0f172a;padding:24px;">'
        '<div style="max-width:680px;margin:0 auto;background:#fff;padding:24px;border-radius:12px;'
        'box-shadow:0 1px 3px rgba(15,23,42,0.08);">'
        f'<h2 style="margin:0 0 6px 0;">PIM Doctor 日检 &nbsp;{_badge(overall)}</h2>'
        f'<p style="margin:0 0 16px 0;color:#64748b;font-size:12px;">检查时间：{html.escape(timestamp)}</p>'
        + "".join(sections)
        + '<p style="margin-top:24px;color:#64748b;font-size:12px;">'
        "本邮件由 DoctorService 在检测到 <code>degraded</code> / <code>error</code> 状态时自动发送，"
        "可在 <code>/api/system/doctor</code> 查看完整 JSON。"
        "</p></div></body></html>"
    )
