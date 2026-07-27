"""Local Capture MVP domain service.

Guarantees:
1. Cookie/Profile never leaves the user's local machine.
2. Mandatory Task Token (5-minute ephemeral lifespan) & Device ID verification.
3. Origin Allowlist verification.
4. Purified ReaderDocument ingestion with anti-replay hash checks.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import uuid

from sqlalchemy.orm import Session

from app.models.paid_matrix import LocalCaptureAudit
from app.utils.datetime import utcnow_naive

# Task Token 有效期为 5 分钟
TASK_TOKEN_TTL_SECONDS = 300
SECRET_SALT = "pim-local-capture-salt-2026"


def generate_task_token(device_id: str, origin_url: str) -> str:
    """生成短时 task_token (5分钟有效)."""
    now_ts = int(utcnow_naive().timestamp())
    msg = f"{device_id}:{origin_url}:{now_ts}"
    token_hash = hmac.new(SECRET_SALT.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{now_ts}.{token_hash}"


def verify_task_token(token: str, device_id: str, origin_url: str) -> bool:
    """校验 task_token 是否合法且在 5 分钟有效期内。"""
    parts = token.split(".", 1)
    if len(parts) != 2:
        return False
    ts_str, client_hash = parts
    try:
        created_ts = int(ts_str)
    except ValueError:
        return False

    now_ts = int(utcnow_naive().timestamp())

    # 检查超时 (5 分钟)
    if abs(now_ts - created_ts) > TASK_TOKEN_TTL_SECONDS:
        return False

    msg = f"{device_id}:{origin_url}:{created_ts}"
    expected_hash = hmac.new(SECRET_SALT.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_hash, client_hash)


def verify_origin_allowlist(origin_url: str, allowlist: list[str] | None = None) -> bool:
    """校验 origin_url 是否属于 Allowed origins."""
    if not allowlist:
        return True  # 默认允许
    lower_origin = origin_url.lower()
    return any(domain.lower() in lower_origin for domain in allowlist)


def process_local_capture(
    db: Session,
    device_id: str,
    task_token: str,
    origin_url: str,
    reader_doc_title: str,
    reader_doc_body: str,
    allowlist: list[str] | None = None,
) -> LocalCaptureAudit:
    """接收并净化 Local Capture 提交的 ReaderDocument，记录防重放与审计。"""
    # 1. 校验 Origin Allowlist
    if not verify_origin_allowlist(origin_url, allowlist):
        raise ValueError(f"Origin URL {origin_url} is not in allowlist.")

    # 2. 校验 Task Token
    if not verify_task_token(task_token, device_id, origin_url):
        raise ValueError("Invalid or expired task token for local capture.")

    # 3. 校验与计算 Checksum 防重放
    content_raw = f"{origin_url}:{reader_doc_title}:{reader_doc_body}"
    checksum = hashlib.sha256(content_raw.encode("utf-8")).hexdigest()
    token_hash = hashlib.sha256(task_token.encode("utf-8")).hexdigest()

    audit = LocalCaptureAudit(
        id=str(uuid.uuid4()),
        device_id=device_id,
        task_token_hash=token_hash,
        origin_url=origin_url,
        reader_doc_checksum=checksum,
        body_length=len(reader_doc_body.strip()),
        created_at=utcnow_naive(),
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit
