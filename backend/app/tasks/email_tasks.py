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

    backoff_seconds = (0.0, 3.0, 10.0)
    last_err: Exception | None = None
    for delay in backoff_seconds:
        if delay:
            await asyncio.sleep(delay)
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
            last_err = e
            logger.warning("SMTP send failed (will retry if attempts remain): %s", e)
    logger.error("Failed to send email after retries: %s", last_err)
    return False


def render_digest_email(digest: Dict, template: str = "default") -> str:
    """Render digest to HTML email."""
    from jinja2 import Environment

    # 启用自动 HTML 转义，防止用户控制的 title/summary 字段注入 HTML
    _jinja_env = Environment(autoescape=True)
    html_template = _jinja_env.from_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f9f9f9; }
            .container { background-color: #ffffff; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
            .header { background: linear-gradient(135deg, #1890ff, #096dd9); color: white; padding: 40px 30px; border-radius: 10px; margin-bottom: 30px; text-align: center; }
            .header h1 { margin: 0 0 10px 0; font-size: 28px; letter-spacing: 0.5px; }
            .header p { margin: 0; opacity: 0.9; font-size: 16px; }
            .stats { display: inline-block; background: rgba(255,255,255,0.2); padding: 8px 20px; border-radius: 20px; margin-top: 20px; font-size: 14px; }
            .category { margin: 35px 0; }
            .category-title { font-size: 20px; font-weight: 700; margin-bottom: 20px; padding-bottom: 12px; border-bottom: 3px solid #e6f7ff; color: #003a8c; }
            .category-title span { font-weight: 400; color: #8c8c8c; font-size: 14px; margin-left: 8px; }
            .item { border: 1px solid #f0f0f0; padding: 20px; margin: 20px 0; background: #ffffff; border-radius: 10px; transition: all 0.3s; }
            .item-source { color: #8c8c8c; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }
            .item-title { font-size: 18px; font-weight: 600; margin: 8px 0; line-height: 1.4; }
            .item-title a { color: #1f1f1f; text-decoration: none; }
            .item-title a:hover { color: #1890ff; }
            .item-content-wrapper { display: flex; gap: 15px; margin-top: 12px; }
            .item-summary { color: #595959; font-size: 14px; flex: 1; }
            .item-thumbnail { width: 120px; height: 68px; object-fit: cover; border-radius: 6px; background-color: #f0f0f0; }
            .item-translation { color: #389e0d; font-size: 14px; margin: 12px 0; padding: 12px 15px; background: #f6ffed; border-radius: 8px; border-left: 4px solid #52c41a; }
            .item-keywords { margin-top: 15px; }
            .keyword { display: inline-block; background: #fff1f0; color: #cf1322; padding: 3px 10px; border-radius: 15px; font-size: 11px; font-weight: 600; margin-right: 6px; margin-bottom: 6px; }
            .footer { margin-top: 50px; padding-top: 30px; border-top: 1px solid #f0f0f0; color: #bfbfbf; font-size: 12px; text-align: center; }
            .empty { color: #bfbfbf; font-style: italic; padding: 40px; text-align: center; font-size: 16px; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>{{ digest.date }} 资讯简报</h1>
                <div class="stats">今日追踪到 {{ digest.total_items }} 条新动态</div>
            </div>

            {% for cat_key, cat_name in [('websites', '网站与博客专栏'), ('x_accounts', 'X (Twitter) 动态'), ('youtube', 'YouTube 视频更新'), ('podcasts', '播客节目')] %}
            {% set category = digest.categories[cat_key] %}
            {% if category.count > 0 %}
            <div class="category">
                <div class="category-title">{{ cat_name }} <span>共 {{ category.count }} 篇</span></div>
                {% for item in category.items %}
                <div class="item">
                    <div class="item-source">{{ item.source_name }}</div>
                    <div class="item-title"><a href="{{ item.url }}" target="_blank">{{ item.title }}</a></div>
                    
                    <div class="item-content-wrapper">
                        {% if item.metadata and item.metadata.thumbnail %}
                        <img src="{{ item.metadata.thumbnail }}" class="item-thumbnail" alt="thumbnail">
                        {% endif %}
                        
                        {% if item.summary %}
                        <div class="item-summary">{{ item.summary }}</div>
                        {% endif %}
                    </div>

                    {% if item.translated_summary %}
                    <div class="item-translation">
                        <strong>AI 翻译摘要：</strong><br>
                        {{ item.translated_summary }}
                    </div>
                    {% endif %}

                    {% if item.keyword_matches %}
                    <div class="item-keywords">
                        {% for kw in item.keyword_matches %}
                        <span class="keyword"># {{ kw.keyword }}</span>
                        {% endfor %}
                    </div>
                    {% endif %}
                </div>
                {% endfor %}
            </div>
            {% endif %}
            {% endfor %}

            {% if digest.total_items == 0 %}
            <div class="empty">🍵 今日清闲，暂无监控更新</div>
            {% endif %}

            <div class="footer">
                <p>Personal Information Monitor | 数字化资讯追踪系统</p>
                <p>生成时间: {{ now }}</p>
            </div>
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
        from app.services.doctor_service import DoctorService

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

    subject = f"PIM Doctor: {overall.upper()} ({date.today().isoformat()})"
    html_body = _render_doctor_digest_html(report)

    sent_any = False
    for recipient in recipients:
        if await send_email(recipient, subject, html_body):
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
