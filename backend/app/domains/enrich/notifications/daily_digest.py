"""Daily digest email rendering + scheduled delivery.

Two public entry points:

* :func:`render_digest_email` – pure HTML rendering, given a digest
  dict from :class:`app.domains.enrich.digest.DigestService`.
* :func:`send_daily_digest_emails` – scheduler-driven orchestrator:
  loads every enabled :class:`EmailSchedule`, generates the day's
  digest, renders it, and dispatches via the platform SMTP transport.

Phase 4 step 7 of the refactor extracted both from the legacy
``app.tasks.email_tasks`` module.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Dict

from app.platform.notifications.smtp import send_email
from app.utils.datetime import today_in_user_timezone, utcnow_naive
from app.utils.logger import get_logger

logger = get_logger(__name__)


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
        from app.domains.enrich.digest import DigestService

        db = SessionLocal()
        try:
            schedules = db.query(EmailSchedule).filter(EmailSchedule.enabled == True).all()
            if not schedules:
                logger.info("No email schedules configured")
                return []

            digest_service = DigestService(db)
            tasks = []

            for schedule in schedules:
                today = today_in_user_timezone()
                today_weekday = today.weekday()
                schedule_days = schedule.schedule_days or [1, 2, 3, 4, 5]
                if today_weekday + 1 not in schedule_days and today_weekday not in schedule_days:
                    continue

                content_filter = schedule.content_filter or {}
                digest = digest_service.generate_daily_digest(
                    date=today,
                    keyword_ids=content_filter.get("keyword_ids"),
                    unread_only=content_filter.get("unread_only", True)
                )

                html_body = render_digest_email(digest, schedule.template)
                digest_id = f"daily:{today.isoformat()}:{schedule.id}"
                from app.platform.persistence.lineage import add_lineage_edge

                for category in (digest.get("categories") or {}).values():
                    for item in category.get("items") or []:
                        content_id = item.get("id")
                        if content_id:
                            add_lineage_edge(
                                from_type="content",
                                from_id=str(content_id),
                                to_type="digest",
                                to_id=digest_id,
                                relation="included_in",
                                session=db,
                            )

                for recipient in schedule.recipients or []:
                    subject = schedule.subject_template.format(date=today.isoformat())
                    tasks.append((recipient, subject, html_body, digest_id))

                schedule.last_sent_at = utcnow_naive()

            db.commit()
            return tasks
        finally:
            db.close()

    email_tasks = await asyncio.to_thread(_build_and_send)

    sent = 0
    for task in email_tasks:
        recipient, subject, html_body = task[:3]
        digest_id = task[3] if len(task) > 3 else f"daily:{subject}"
        if await send_email(
            recipient,
            subject,
            html_body,
            idempotency_key=f"daily-digest:{recipient}:{subject}",
            aggregate_type="digest",
            aggregate_id=digest_id,
        ):
            sent += 1

    logger.info(f"Sent {sent} digest emails")
