"""Paid-source Matrix, Session Recovery演练, and Daily Canary domain service."""

from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy.orm import Session

from app.models.paid_matrix import DailyCanaryRun, PaidSourceMatrixAudit, SessionRecoveryAudit
from app.models.source import Source
from app.utils.datetime import utcnow_naive

# 判定为有效正文的最小字符长度门禁
MIN_READABLE_BODY_LENGTH = 100

# 常见的付费墙遮挡特征词 (Paywall residual keywords)
PAYWALL_KEYWORDS = [
    "subscribe to read",
    "become a member",
    "exclusive for subscribers",
    "paywall",
    "create an account to continue reading",
    "订阅解锁全文",
    "付费阅读",
]


def check_readability(body_text: str | None) -> tuple[bool, str | None]:
    """判断抓取到的正文是否为真实可读正文，而非单纯的 HTTP 200 / Paywall 页面。"""
    if not body_text or len(body_text.strip()) < MIN_READABLE_BODY_LENGTH:
        return False, "BODY_TOO_SHORT"

    lower_text = body_text.lower()
    for kw in PAYWALL_KEYWORDS:
        if kw in lower_text:
            return False, "PAYWALL_RESIDUAL_DETECTED"

    return True, None


def record_paid_source_result(
    db: Session,
    source_id: str,
    body_text: str | None,
    discovery_url: str | None = None,
    validation_url: str | None = None,
    http_status: int = 200,
) -> PaidSourceMatrixAudit:
    """根据正文可读性结果更新 Paid-source Matrix，绝不以 HTTP 200 为准。"""
    is_readable, failure_code = check_readability(body_text)

    now = utcnow_naive()
    last_success = now if is_readable else None

    if http_status != 200 and not failure_code:
        failure_code = f"HTTP_{http_status}"

    recovery_action = None
    if not is_readable:
        if failure_code == "PAYWALL_RESIDUAL_DETECTED":
            recovery_action = "RE_AUTHENTICATE_COOKIE"
        elif failure_code == "BODY_TOO_SHORT":
            recovery_action = "CHECK_SELECTOR_OR_PARSER"
        else:
            recovery_action = "INSPECT_NETWORK_AND_PROXY"

    audit = PaidSourceMatrixAudit(
        id=str(uuid.uuid4()),
        source_id=source_id,
        discovery_url=discovery_url,
        validation_url=validation_url,
        last_readable_success_at=last_success,
        success_rate_7d=1.0 if is_readable else 0.0,
        failure_code=failure_code,
        recovery_action=recovery_action,
        created_at=now,
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


def trigger_session_expiration(db: Session, auth_config_id: str, root_cause: str = "MANUAL_TEST_EXPIRATION") -> SessionRecoveryAudit:
    """主动失效测试会话，开启 Session Recovery 演练。"""
    audit = SessionRecoveryAudit(
        id=str(uuid.uuid4()),
        auth_config_id=auth_config_id,
        detected_at=utcnow_naive(),
        root_cause=root_cause,
        status="detected",
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


def ack_session_recovery(db: Session, audit_id: str) -> SessionRecoveryAudit | None:
    """确认告警 (Ack)."""
    audit = db.query(SessionRecoveryAudit).filter(SessionRecoveryAudit.id == audit_id).first()
    if audit and audit.status == "detected":
        audit.acked_at = utcnow_naive()
        audit.status = "acked"
        db.commit()
        db.refresh(audit)
    return audit


def complete_session_recovery(db: Session, audit_id: str) -> SessionRecoveryAudit | None:
    """会话重新登录/恢复完成 (Recover)，计算 MTTR (秒)."""
    audit = db.query(SessionRecoveryAudit).filter(SessionRecoveryAudit.id == audit_id).first()
    if audit and audit.status in ("detected", "acked"):
        now = utcnow_naive()
        audit.recovered_at = now
        audit.status = "recovered"
        delta = (now - audit.detected_at).total_seconds()
        audit.mttr_seconds = max(0.0, delta)
        db.commit()
        db.refresh(audit)
    return audit


def run_daily_canary_for_source(
    db: Session,
    source_id: str,
    sample_body: str | None,
    run_date_str: str | None = None,
) -> DailyCanaryRun:
    """对特定付费源执行每日 Canary 探针抓取验证。"""
    if not run_date_str:
        run_date_str = utcnow_naive().strftime("%Y-%m-%d")

    is_readable, reason = check_readability(sample_body)

    paywall_detected = (reason == "PAYWALL_RESIDUAL_DETECTED")
    status = "success" if is_readable else ("degraded" if paywall_detected else "failed")
    body_len = len(sample_body.strip()) if sample_body else 0

    canary_run = DailyCanaryRun(
        id=str(uuid.uuid4()),
        source_id=source_id,
        run_date=run_date_str,
        status=status,
        body_length=body_len,
        paywall_residual_detected=paywall_detected,
        error_message=reason,
        created_at=utcnow_naive(),
    )
    db.add(canary_run)
    db.commit()
    db.refresh(canary_run)
    return canary_run
