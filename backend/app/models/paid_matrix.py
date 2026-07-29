"""Paid-source matrix, Session recovery, Local capture, Daily canary, and Auth Archive extraction models."""

import enum
import uuid

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from app.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class PaidSourceMatrixAudit(Base):
    """付费源防回归矩阵日志。"""

    __tablename__ = "paid_source_matrix_audits"

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id = Column(UUIDString, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    discovery_url = Column(Text, nullable=True)
    validation_url = Column(Text, nullable=True)
    last_readable_success_at = Column(DateTime, nullable=True)
    success_rate_7d = Column(Float, default=1.0, nullable=False)
    failure_code = Column(String(50), nullable=True)
    recovery_action = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)

    source = relationship("Source")


class SessionRecoveryAudit(Base):
    """会话恢复演练审计表 (MTTR Tracking)。"""

    __tablename__ = "session_recovery_audits"

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    auth_config_id = Column(UUIDString, ForeignKey("auth_configs.id", ondelete="CASCADE"), nullable=False)
    detected_at = Column(DateTime, default=utcnow_naive, nullable=False)
    acked_at = Column(DateTime, nullable=True)
    recovered_at = Column(DateTime, nullable=True)
    root_cause = Column(Text, nullable=True)
    mttr_seconds = Column(Float, nullable=True)
    status = Column(String(20), default="detected", nullable=False)  # detected, acked, recovered
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)

    auth_config = relationship("AuthConfig")


class LocalCaptureAudit(Base):
    """本地捕获 MVP 净化 ReaderDocument 审计。"""

    __tablename__ = "local_capture_audits"
    __table_args__ = (Index("uq_local_capture_task_token_hash", "task_token_hash", unique=True),)

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id = Column(String(100), nullable=False)
    task_token_hash = Column(String(100), nullable=False)
    origin_url = Column(Text, nullable=False)
    reader_doc_checksum = Column(String(100), nullable=False)
    body_length = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)


class DailyCanaryRun(Base):
    """每日 Canary 探针运行记录。"""

    __tablename__ = "daily_canary_runs"
    __table_args__ = (Index("idx_daily_canary_source_date", "source_id", "run_date", unique=True),)

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id = Column(UUIDString, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    run_date = Column(String(10), nullable=False)  # YYYY-MM-DD
    status = Column(String(20), nullable=False)  # success, failed, degraded
    body_length = Column(Integer, default=0, nullable=False)
    paywall_residual_detected = Column(Boolean, default=False, nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)

    source = relationship("Source")


class AuthArchiveExtraction(Base):
    """受权 Archive (ZIP) 流式解压审计。"""

    __tablename__ = "auth_archive_extractions"

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    archive_name = Column(String(255), nullable=False)
    entry_count = Column(Integer, default=0, nullable=False)
    uncompressed_bytes = Column(BigInteger, default=0, nullable=False)
    compression_ratio = Column(Float, default=1.0, nullable=False)
    status = Column(String(20), nullable=False)  # success, rejected, failed
    rejection_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)
