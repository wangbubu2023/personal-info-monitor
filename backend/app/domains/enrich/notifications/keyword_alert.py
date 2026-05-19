"""Keyword match alert email.

Single coroutine :func:`send_keyword_alert` that, given a content ID +
matched keyword, looks up the content row, validates the keyword's
``notify_email`` flag, and dispatches an HTML-escaped alert to every
recipient configured on enabled :class:`EmailSchedule` rows (falling
back to ``SMTP_USER`` if none).

Phase 4 step 7 of the refactor extracted this from the legacy
``app.tasks.email_tasks`` module.
"""

from __future__ import annotations

import asyncio
import html
import re

from app.platform.notifications.smtp import send_email
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def send_keyword_alert(content_id: str, keyword: str, title: str):
    """Send an alert when a keyword is matched."""
    logger.info(f"Sending keyword alert for: {keyword}")

    def _build_alert():
        from app.database import SessionLocal
        from app.models import Content, EmailSchedule, Keyword

        db = SessionLocal()
        try:
            content = db.query(Content).filter(Content.id == content_id).first()
            keyword_obj = db.query(Keyword).filter(Keyword.keyword == keyword).first()

            if not content or not keyword_obj:
                return None
            if not keyword_obj.notify_email:
                return None

            safe_keyword = html.escape(str(keyword or ""))
            safe_title = html.escape(str(content.title or ""))
            safe_summary = html.escape(str(content.summary or ""))
            safe_url = html.escape(str(content.original_url or ""), quote=True)
            safe_color = str(keyword_obj.color or "#1890ff").strip()
            if not re.fullmatch(r"#?[0-9A-Fa-f]{3,8}", safe_color):
                safe_color = "#1890ff"
            if not safe_color.startswith("#"):
                safe_color = f"#{safe_color}"

            html_body = f"""
            <html>
            <body style="font-family: sans-serif; padding: 20px;">
                <h2>关键词匹配提醒</h2>
                <p>检测到包含关键词 <strong style="color: {safe_color};">「{safe_keyword}」</strong> 的新内容：</p>
                <div style="border-left: 3px solid #1890ff; padding: 15px; margin: 15px 0; background: #f5f5f5;">
                    <h3 style="margin: 0 0 10px 0;"><a href="{safe_url}">{safe_title}</a></h3>
                    <p style="color: #666;">{safe_summary}</p>
                </div>
                <p style="color: #999; font-size: 12px;">由 Personal Information Monitor 自动发送</p>
            </body>
            </html>
            """

            from app.config import get_settings
            settings = get_settings()

            recipients = set()
            schedules = db.query(EmailSchedule).filter(EmailSchedule.enabled == True).all()
            for schedule in schedules:
                for r in schedule.recipients or []:
                    email = str(r or "").strip()
                    if email:
                        recipients.add(email)

            if not recipients and settings.smtp_user:
                recipients.add(settings.smtp_user)

            return [(r, f"关键词匹配：{keyword}", html_body) for r in recipients]
        finally:
            db.close()

    tasks = await asyncio.to_thread(_build_alert)
    if not tasks:
        return

    for recipient, subject, html_body in tasks:
        await send_email(recipient, subject, html_body)
