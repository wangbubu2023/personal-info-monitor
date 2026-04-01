"""Tasks for sending emails."""

import asyncio
import html
import re
from datetime import date, datetime
from typing import Dict, List, Optional

from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def send_email(
    to: str,
    subject: str,
    html_body: str,
    from_email: Optional[str] = None
):
    """Send an email using SMTP."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    import aiosmtplib

    from app.config import get_settings
    settings = get_settings()

    if not settings.smtp_user or not settings.smtp_password:
        logger.warning("SMTP not configured, skipping email")
        return False

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = from_email or settings.smtp_user
    message["To"] = to

    html_part = MIMEText(html_body, "html")
    message.attach(html_part)

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            start_tls=True,
        )
        logger.info(f"Email sent to {to}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


def render_digest_email(digest: Dict, template: str = "default") -> str:
    """Render digest to HTML email."""
    from jinja2 import Template

    html_template = Template("""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 20px; }
            .header { background: linear-gradient(135deg, #1890ff, #096dd9); color: white; padding: 30px; border-radius: 10px; margin-bottom: 30px; }
            .header h1 { margin: 0 0 10px 0; font-size: 24px; }
            .header p { margin: 0; opacity: 0.9; }
            .stats { display: flex; gap: 20px; margin-top: 15px; }
            .stat { background: rgba(255,255,255,0.2); padding: 10px 15px; border-radius: 5px; }
            .category { margin: 25px 0; }
            .category-title { font-size: 18px; font-weight: 600; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 2px solid #f0f0f0; }
            .category-title span { font-weight: normal; color: #999; font-size: 14px; }
            .item { border-left: 3px solid #1890ff; padding: 15px; margin: 15px 0; background: #fafafa; border-radius: 0 8px 8px 0; }
            .item-source { color: #1890ff; font-size: 12px; font-weight: 500; margin-bottom: 5px; }
            .item-title { font-size: 16px; font-weight: 600; margin: 5px 0; }
            .item-title a { color: #333; text-decoration: none; }
            .item-title a:hover { color: #1890ff; }
            .item-summary { color: #666; font-size: 14px; margin: 10px 0; }
            .item-translation { color: #52c41a; font-size: 13px; font-style: italic; margin: 8px 0; padding: 8px; background: #f6ffed; border-radius: 4px; }
            .item-keywords { margin-top: 10px; }
            .keyword { display: inline-block; background: #fff2f0; color: #ff4d4f; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin-right: 5px; }
            .footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid #f0f0f0; color: #999; font-size: 12px; text-align: center; }
            .empty { color: #999; font-style: italic; padding: 20px; text-align: center; }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>每日资讯简报</h1>
            <p>{{ digest.date }}</p>
            <div class="stats">
                <div class="stat">今日更新: {{ digest.total_items }} 条</div>
            </div>
        </div>

        {% for cat_key, cat_name in [('websites', '网站/博客'), ('x_accounts', 'X账户'), ('youtube', 'YouTube'), ('podcasts', '播客')] %}
        {% set category = digest.categories[cat_key] %}
        {% if category.count > 0 %}
        <div class="category">
            <div class="category-title">{{ cat_name }} <span>({{ category.count }}条)</span></div>
            {% for item in category.items %}
            <div class="item">
                <div class="item-source">{{ item.source_name }}</div>
                <div class="item-title"><a href="{{ item.url }}" target="_blank">{{ item.title }}</a></div>
                {% if item.summary %}
                <div class="item-summary">{{ item.summary }}</div>
                {% endif %}
                {% if item.translated_summary %}
                <div class="item-translation">{{ item.translated_summary }}</div>
                {% endif %}
                {% if item.keyword_matches %}
                <div class="item-keywords">
                    {% for kw in item.keyword_matches %}
                    <span class="keyword">{{ kw.keyword }}</span>
                    {% endfor %}
                </div>
                {% endif %}
            </div>
            {% endfor %}
        </div>
        {% endif %}
        {% endfor %}

        {% if digest.total_items == 0 %}
        <div class="empty">今日暂无更新内容</div>
        {% endif %}

        <div class="footer">
            <p>由 Personal Information Monitor 自动生成</p>
            <p>{{ now }}</p>
        </div>
    </body>
    </html>
    """)

    return html_template.render(digest=digest, now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


async def send_daily_digest_emails():
    """Send daily digest emails to all configured recipients."""
    logger.info("Sending daily digest emails")

    def _build_and_send():
        from app.database import SessionLocal
        from app.models import EmailSchedule
        from app.services.digest_service import DigestService

        db = SessionLocal()
        try:
            schedules = db.query(EmailSchedule).filter(EmailSchedule.enabled == True).all()
            if not schedules:
                logger.info("No email schedules configured")
                return []

            digest_service = DigestService(db)
            tasks = []

            for schedule in schedules:
                today_weekday = date.today().weekday()
                schedule_days = schedule.schedule_days or [1, 2, 3, 4, 5]
                if today_weekday + 1 not in schedule_days and today_weekday not in schedule_days:
                    continue

                content_filter = schedule.content_filter or {}
                digest = digest_service.generate_daily_digest(
                    date=date.today(),
                    category_ids=content_filter.get("categories"),
                    keyword_ids=content_filter.get("keyword_ids"),
                    unread_only=content_filter.get("unread_only", True)
                )

                html_body = render_digest_email(digest, schedule.template)

                for recipient in schedule.recipients or []:
                    subject = schedule.subject_template.format(date=date.today().isoformat())
                    tasks.append((recipient, subject, html_body))

                schedule.last_sent_at = utcnow_naive()

            db.commit()
            return tasks
        finally:
            db.close()

    email_tasks = await asyncio.to_thread(_build_and_send)

    sent = 0
    for recipient, subject, html_body in email_tasks:
        if await send_email(recipient, subject, html_body):
            sent += 1

    logger.info(f"Sent {sent} digest emails")


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
