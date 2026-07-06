"""Weekly operator health report email.

Unlike the doctor digest (which stays silent on green to avoid alert
fatigue), the weekly report always sends when SMTP is configured: its job
is to force a periodic look at trend metrics that otherwise go unread.
Principle: a metric that never reaches a push channel does not exist.

Content (last 7 days, all computed from structured storage — no metadata
JSON scraping):

- fetch attempts / success / failure / empty totals (``source_fetch_log``)
- top failing sources with their dominant failure code
- fulltext hydration rate (``fulltext_ok`` / ``fulltext_total`` sums)
- new content volume (``contents.fetched_at`` window count)
- sources currently in a non-ok session-health state (paywall / X cookies)
- sources currently disabled or in cooldown

Scheduled Monday 08:10 Asia/Shanghai (see :mod:`app.scheduler`), right
after the daily digest + doctor emails so the operator gets one combined
morning triage block at the start of the week.
"""

from __future__ import annotations

import asyncio
import html
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict

from sqlalchemy import func

from app.platform.notifications.smtp import send_email
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger

logger = get_logger(__name__)

_TOP_FAILING_LIMIT = 5
_DEFAULT_EVAL_HISTORY = Path.home() / ".pim" / "data" / "eval_history.jsonl"
_EVAL_METRICS = (
    "precision@20",
    "duplicate_rate",
    "fulltext_complete_rate",
    "source_coverage@20",
)


def _load_eval_history_summary(
    history_path: Path = _DEFAULT_EVAL_HISTORY,
    *,
    max_points: int = 4,
) -> Dict[str, Any] | None:
    """Read recent offline-eval history points for the weekly report."""
    if not history_path.exists():
        return None

    points: list[dict[str, Any]] = []
    with history_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError:
                continue
            metrics = record.get("metrics") if isinstance(record, dict) else None
            if isinstance(metrics, dict):
                points.append(record)

    if not points:
        return None

    recent = points[-max_points:]
    latest = recent[-1]
    previous = recent[-2] if len(recent) >= 2 else None
    latest_metrics = latest.get("metrics") if isinstance(latest.get("metrics"), dict) else {}
    previous_metrics = previous.get("metrics") if previous and isinstance(previous.get("metrics"), dict) else {}
    metrics: dict[str, Any] = {}
    for key in _EVAL_METRICS:
        value = latest_metrics.get(key)
        prev_value = previous_metrics.get(key)
        delta = None
        if isinstance(value, (int, float)) and isinstance(prev_value, (int, float)):
            delta = round(value - prev_value, 4)
        metrics[key] = {"value": value, "previous": prev_value, "delta": delta}

    return {
        "history_path": str(history_path),
        "points": len(points),
        "recent_points": len(recent),
        "latest_ran_at": latest.get("ran_at"),
        "metrics": metrics,
    }


def build_weekly_health_report(
    db,
    *,
    now: datetime | None = None,
    days: int = 7,
    eval_history_path: Path = _DEFAULT_EVAL_HISTORY,
) -> Dict[str, Any]:
    """Aggregate the last ``days`` of fetch/content/session health into a dict.

    Pure read-only aggregation over structured columns; safe to call from
    API handlers or tests with any sync Session.
    """
    from app.models import Content, Source
    from app.models.source_fetch_log import SourceFetchLog

    now = now or utcnow_naive()
    window_start = now - timedelta(days=days)

    outcome_rows = (
        db.query(SourceFetchLog.outcome, func.count(SourceFetchLog.id))
        .filter(SourceFetchLog.attempted_at >= window_start)
        .group_by(SourceFetchLog.outcome)
        .all()
    )
    outcomes = {str(outcome): int(count) for outcome, count in outcome_rows}
    attempts = sum(outcomes.values())

    fulltext_ok, fulltext_total = (
        db.query(
            func.coalesce(func.sum(SourceFetchLog.fulltext_ok), 0),
            func.coalesce(func.sum(SourceFetchLog.fulltext_total), 0),
        )
        .filter(SourceFetchLog.attempted_at >= window_start)
        .one()
    )

    failing_rows = (
        db.query(
            SourceFetchLog.source_id,
            func.count(SourceFetchLog.id).label("failures"),
            func.max(SourceFetchLog.failure_code).label("failure_code"),
        )
        .filter(
            SourceFetchLog.attempted_at >= window_start,
            SourceFetchLog.outcome == "failure",
        )
        .group_by(SourceFetchLog.source_id)
        .order_by(func.count(SourceFetchLog.id).desc())
        .limit(_TOP_FAILING_LIMIT)
        .all()
    )
    source_names = {}
    if failing_rows:
        ids = [row.source_id for row in failing_rows]
        source_names = {
            str(sid): name
            for sid, name in db.query(Source.id, Source.name).filter(Source.id.in_(ids)).all()
        }
    top_failing = [
        {
            "source_id": str(row.source_id),
            "source_name": source_names.get(str(row.source_id), str(row.source_id)),
            "failures": int(row.failures),
            "failure_code": row.failure_code,
        }
        for row in failing_rows
    ]

    session_issues = [
        {
            "source_name": source.name,
            "status": source.session_health_status,
            "reason": source.session_health_reason,
        }
        for source in (
            db.query(Source)
            .filter(
                Source.session_health_status.isnot(None),
                Source.session_health_status != "ok",
            )
            .order_by(Source.name)
            .all()
        )
    ]

    disabled_count = int(
        db.query(func.count(Source.id)).filter(Source.enabled == False).scalar() or 0  # noqa: E712
    )
    cooldown_count = int(
        db.query(func.count(Source.id)).filter(Source.fetch_cooldown_until > now).scalar() or 0
    )
    new_content_count = int(
        db.query(func.count(Content.id)).filter(Content.fetched_at >= window_start).scalar() or 0
    )

    return {
        "window_days": days,
        "window_start": window_start.isoformat(),
        "generated_at": now.isoformat(),
        "fetch": {
            "attempts": attempts,
            "success": outcomes.get("success", 0),
            "failure": outcomes.get("failure", 0),
            "empty": outcomes.get("empty", 0),
            "fulltext_ok": int(fulltext_ok),
            "fulltext_total": int(fulltext_total),
            "fulltext_rate": round(int(fulltext_ok) / int(fulltext_total), 4) if int(fulltext_total) else None,
        },
        "top_failing_sources": top_failing,
        "session_issues": session_issues,
        "disabled_sources": disabled_count,
        "cooldown_sources": cooldown_count,
        "new_content_count": new_content_count,
        "offline_eval": _load_eval_history_summary(eval_history_path),
    }


def _render_weekly_report_html(report: Dict[str, Any]) -> str:
    """Render the aggregation dict as a self-contained HTML email body."""

    def esc(value: Any) -> str:
        return html.escape(str(value if value is not None else "—"))

    fetch = report.get("fetch", {})
    fulltext_rate = fetch.get("fulltext_rate")
    fulltext_pct = f"{fulltext_rate * 100:.1f}%" if isinstance(fulltext_rate, (int, float)) else "—"

    failing_rows = "".join(
        f"<tr><td style='padding:4px 12px'>{esc(row.get('source_name'))}</td>"
        f"<td style='padding:4px 12px;text-align:right'>{esc(row.get('failures'))}</td>"
        f"<td style='padding:4px 12px'>{esc(row.get('failure_code'))}</td></tr>"
        for row in report.get("top_failing_sources", [])
    ) or "<tr><td colspan='3' style='padding:4px 12px'>无失败记录</td></tr>"

    session_rows = "".join(
        f"<tr><td style='padding:4px 12px'>{esc(row.get('source_name'))}</td>"
        f"<td style='padding:4px 12px'>{esc(row.get('status'))}</td>"
        f"<td style='padding:4px 12px'>{esc(row.get('reason'))}</td></tr>"
        for row in report.get("session_issues", [])
    ) or "<tr><td colspan='3' style='padding:4px 12px'>全部正常</td></tr>"

    eval_report = report.get("offline_eval")
    if eval_report:
        eval_metrics = eval_report.get("metrics", {})

        def render_metric(name: str) -> str:
            item = eval_metrics.get(name, {})
            value = item.get("value")
            delta = item.get("delta")
            delta_text = "—" if delta is None else f"{delta:+.4f}"
            return (
                f"<tr><td style='padding:4px 12px'>{esc(name)}</td>"
                f"<td style='padding:4px 12px;text-align:right'>{esc(value)}</td>"
                f"<td style='padding:4px 12px;text-align:right'>{esc(delta_text)}</td></tr>"
            )

        eval_rows = "".join(render_metric(name) for name in _EVAL_METRICS)
        eval_section = f"""
  <h3>离线评测趋势</h3>
  <p style="color:#64748b;margin-top:0">最近点：{esc(eval_report.get('latest_ran_at'))} · 历史点 {esc(eval_report.get('points'))}</p>
  <table style="border-collapse:collapse;font-size:14px">
    <tr style="text-align:left;color:#64748b"><th style="padding:4px 12px">指标</th><th style="padding:4px 12px">最新</th><th style="padding:4px 12px">较上次</th></tr>
    {eval_rows}
  </table>
"""
    else:
        eval_section = """
  <h3>离线评测趋势</h3>
  <p>暂无离线评测历史；安装 500 条人工标注集并运行 offline eval 后会出现在这里。</p>
"""

    return f"""
<div style="font-family:system-ui,-apple-system,sans-serif;max-width:640px">
  <h2 style="margin-bottom:4px">PIM 每周体检（近 {esc(report.get('window_days'))} 天）</h2>
  <p style="color:#64748b;margin-top:0">生成时间：{esc(report.get('generated_at'))}</p>

  <h3>抓取</h3>
  <p>
    尝试 {esc(fetch.get('attempts'))} 次 ·
    成功 {esc(fetch.get('success'))} ·
    失败 {esc(fetch.get('failure'))} ·
    空结果 {esc(fetch.get('empty'))}<br/>
    正文完整率 {esc(fulltext_pct)}（{esc(fetch.get('fulltext_ok'))}/{esc(fetch.get('fulltext_total'))}）·
    新入库内容 {esc(report.get('new_content_count'))} 条
  </p>

  <h3>失败 Top {_TOP_FAILING_LIMIT} 源</h3>
  <table style="border-collapse:collapse;font-size:14px">
    <tr style="text-align:left;color:#64748b"><th style="padding:4px 12px">源</th><th style="padding:4px 12px">失败次数</th><th style="padding:4px 12px">失败码</th></tr>
    {failing_rows}
  </table>

  <h3>会话健康（付费墙 / X 登录态）</h3>
  <table style="border-collapse:collapse;font-size:14px">
    <tr style="text-align:left;color:#64748b"><th style="padding:4px 12px">源</th><th style="padding:4px 12px">状态</th><th style="padding:4px 12px">原因</th></tr>
    {session_rows}
  </table>

  <h3>调度状态</h3>
  <p>禁用源 {esc(report.get('disabled_sources'))} 个 · 冷却中 {esc(report.get('cooldown_sources'))} 个</p>

  {eval_section}
</div>
"""


async def send_weekly_health_report_email() -> bool:
    """Build and send the weekly health report to configured recipients.

    No-op (returns False) when SMTP is unconfigured. Recipient resolution
    mirrors the doctor digest: every enabled ``EmailSchedule`` recipient,
    falling back to ``SMTP_USER``.
    """
    from app.config import get_settings

    settings = get_settings()
    if not settings.smtp_user or not settings.smtp_password:
        logger.info("Skipping weekly health report: SMTP is not configured")
        return False

    def _build() -> tuple[Dict[str, Any], list[str]]:
        from app.database import SessionLocal
        from app.models import EmailSchedule

        db = SessionLocal()
        try:
            report = build_weekly_health_report(db)
            recipients: set[str] = set()
            schedules = db.query(EmailSchedule).filter(EmailSchedule.enabled == True).all()  # noqa: E712
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

    report, recipients = await asyncio.to_thread(_build)
    if not recipients:
        logger.warning("Weekly health report: no recipients configured")
        return False

    subject = f"PIM 每周体检 ({date.today().isoformat()})"
    html_body = _render_weekly_report_html(report)

    sent_any = False
    for recipient in recipients:
        if await send_email(recipient, subject, html_body):
            sent_any = True
    if sent_any:
        logger.info("Sent weekly health report to %d recipient(s)", len(recipients))
    return sent_any
