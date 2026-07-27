"""Brief (Weekly/Monthly) generation, Lineage tracking, and Fact Modality Lattice domain service."""

import uuid

from sqlalchemy.orm import Session

from app.models.brief import BriefSnapshot, MODALITY_SCORE_MAP, ModalityAuditLog, ModalityLevel
from app.models.content_event import ContentEventSnapshot
from app.utils.datetime import utcnow_naive


def validate_modality_lattice(upstream_modality: str, brief_modality: str) -> tuple[bool, str | None]:
    """验证事实模态阶梯守恒性 (Modality Lattice Invariant).
    规则: 下一级 (brief_modality) 的确定程度不得高于上游 (upstream_modality)。
    """
    up_enum = ModalityLevel(upstream_modality) if upstream_modality in ModalityLevel.__members__.values() else ModalityLevel.REPORTED
    br_enum = ModalityLevel(brief_modality) if brief_modality in ModalityLevel.__members__.values() else ModalityLevel.REPORTED

    up_score = MODALITY_SCORE_MAP.get(up_enum, 7)
    br_score = MODALITY_SCORE_MAP.get(br_enum, 7)

    if br_score > up_score:
        return False, f"Modality Inversion Violation: Brief assertion level '{brief_modality}' (score {br_score}) exceeds upstream Level '{upstream_modality}' (score {up_score})."

    return True, None


def create_brief_snapshot(
    db: Session,
    period_key: str,
    brief_type: str,
    title: str,
    summary_content: str,
    upstream_event_snapshot_ids: list[str],
    upstream_modality: str = "reported",
    brief_modality: str = "reported",
    generator_version: str = "v1.0",
) -> tuple[BriefSnapshot, ModalityAuditLog | None]:
    """创建或更新不可变 Brief 快照，带完整 Lineage 血统与 Modality Lattice 守恒检查。"""
    if brief_type not in ("weekly", "monthly"):
        raise ValueError("brief_type must be either 'weekly' or 'monthly'")

    # 1. 模态守恒检查
    is_valid, violation_msg = validate_modality_lattice(upstream_modality, brief_modality)

    modality_status = "valid" if is_valid else "violation_flagged"

    lineage = {
        "source_event_snapshot_ids": upstream_event_snapshot_ids,
        "input_version": 1,
        "generator_version": generator_version,
        "period_key": period_key,
        "upstream_modality": upstream_modality,
        "brief_modality": brief_modality,
    }

    now = utcnow_naive()
    # 检查已存在快照 (Immutable release check)
    existing = (
        db.query(BriefSnapshot)
        .filter(BriefSnapshot.period_key == period_key, BriefSnapshot.brief_type == brief_type)
        .first()
    )

    if existing:
        brief = existing
        brief.title = title
        brief.summary_content = summary_content
        brief.lineage_snapshot = lineage
        brief.modality_status = modality_status
        brief.updated_at = now
    else:
        brief = BriefSnapshot(
            id=str(uuid.uuid4()),
            period_key=period_key,
            brief_type=brief_type,
            title=title,
            summary_content=summary_content,
            lineage_snapshot=lineage,
            modality_status=modality_status,
            created_at=now,
            updated_at=now,
        )
        db.add(brief)

    db.commit()
    db.refresh(brief)

    audit_log = None
    if not is_valid:
        audit_log = ModalityAuditLog(
            id=str(uuid.uuid4()),
            brief_id=brief.id,
            upstream_modality=upstream_modality,
            brief_modality=brief_modality,
            violation_reason=violation_msg,
            created_at=now,
        )
        db.add(audit_log)
        db.commit()
        db.refresh(audit_log)

    return brief, audit_log


def override_brief_modality_violation(
    db: Session,
    brief_id: str,
    override_by: str,
    override_reason: str,
) -> BriefSnapshot:
    """人工 Override 解除模态违规标记（需提供独立理由与操作审计）。"""
    brief = db.query(BriefSnapshot).filter(BriefSnapshot.id == brief_id).first()
    if not brief:
        raise ValueError(f"Brief {brief_id} not found.")

    brief.modality_status = "override_approved"

    log = db.query(ModalityAuditLog).filter(ModalityAuditLog.brief_id == brief_id).first()
    if log:
        log.override_by = override_by
        log.override_reason = override_reason

    db.commit()
    db.refresh(brief)
    return brief
