"""Brief snapshot and fact modality lattice models."""

import enum
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from app.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class ModalityLevel(str, enum.Enum):
    """事实模态偏序阶梯 (Modality Lattice order)。
    数值越大代表断言的确定程度越高。下一级 (Brief) 的确定度不得超过上游 (Snapshot)。
    """

    RETRACTED = "retracted"  # 1
    DISPUTED = "disputed"    # 2
    DENIED = "denied"        # 3
    QUESTION = "question"    # 4
    ALLEGED = "alleged"      # 5
    PLANNED = "planned"      # 6
    REPORTED = "reported"    # 7
    CONFIRMED = "confirmed"  # 8


MODALITY_SCORE_MAP = {
    ModalityLevel.RETRACTED: 1,
    ModalityLevel.DISPUTED: 2,
    ModalityLevel.DENIED: 3,
    ModalityLevel.QUESTION: 4,
    ModalityLevel.ALLEGED: 5,
    ModalityLevel.PLANNED: 6,
    ModalityLevel.REPORTED: 7,
    ModalityLevel.CONFIRMED: 8,
}


class BriefSnapshot(Base):
    """周报/月报不可变 Brief 快照实体。"""

    __tablename__ = "brief_snapshots"
    __table_args__ = (
        Index("idx_brief_period_type_version_unique", "period_key", "brief_type", "version", unique=True),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    period_key = Column(String(50), nullable=False)  # 例如 "2026-W30" 或 "2026-07"
    brief_type = Column(String(20), nullable=False)  # "weekly" 或 "monthly"
    version = Column(Integer, nullable=False, default=1)
    title = Column(String(255), nullable=False)
    summary_content = Column(Text, nullable=False)

    # Lineage 血统元数据: {"source_event_snapshot_ids": [...], "input_version": 1, "generator_version": "v1.0"}
    lineage_snapshot = Column(JSON, nullable=False, default=dict)
    modality_status = Column(String(30), default="valid", nullable=False)  # valid, violation_flagged, override_approved
    modality_violation_count = Column(Integer, default=0, nullable=False)
    publication_status = Column(String(20), default="published", nullable=False)  # published, blocked

    created_at = Column(DateTime, default=utcnow_naive, nullable=False)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive, nullable=False)

    audit_logs = relationship("ModalityAuditLog", back_populates="brief", cascade="all, delete-orphan")


class ModalityAuditLog(Base):
    """模态违规与人工 Override 审计日志。"""

    __tablename__ = "modality_audit_logs"

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    brief_id = Column(UUIDString, ForeignKey("brief_snapshots.id", ondelete="CASCADE"), nullable=False)
    upstream_modality = Column(String(30), nullable=False)
    brief_modality = Column(String(30), nullable=False)
    violation_reason = Column(Text, nullable=True)
    override_by = Column(String(100), nullable=True)
    override_reason = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utcnow_naive, nullable=False)

    brief = relationship("BriefSnapshot", back_populates="audit_logs")
