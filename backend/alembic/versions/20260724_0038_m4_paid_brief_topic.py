"""M4 Paid sources, Briefs, Topics, and Fact Modality Lattice.

Revision ID: 20260724_0038
Revises: 20260724_0037
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.database import UUIDString

revision = "20260724_0038"
down_revision = "20260724_0037"
branch_labels = None
depends_on = None


def _table(name: str) -> bool:
    """检查数据库表是否存在。"""
    return sa.inspect(op.get_bind()).has_table(name)


def _columns(table: str) -> set[str]:
    """获取数据库表的所有列名集合。"""
    return {row["name"] for row in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    """获取数据库表的所有索引名集合。"""
    return {row["name"] for row in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    """升级数据库结构至 M4 版本。"""
    bind = op.get_bind()

    # 1. 付费源防回归矩阵日志表
    if not _table("paid_source_matrix_audits"):
        op.create_table(
            "paid_source_matrix_audits",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("source_id", UUIDString, sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
            sa.Column("discovery_url", sa.Text, nullable=True),
            sa.Column("validation_url", sa.Text, nullable=True),
            sa.Column("last_readable_success_at", sa.DateTime, nullable=True),
            sa.Column("success_rate_7d", sa.Float, default=1.0, nullable=False),
            sa.Column("failure_code", sa.String(50), nullable=True),
            sa.Column("recovery_action", sa.String(100), nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )
        op.create_index("idx_paid_matrix_source_id", "paid_source_matrix_audits", ["source_id"])

    # 2. 会话恢复演练审计表
    if not _table("session_recovery_audits"):
        op.create_table(
            "session_recovery_audits",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("auth_config_id", UUIDString, sa.ForeignKey("auth_configs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("detected_at", sa.DateTime, nullable=False),
            sa.Column("acked_at", sa.DateTime, nullable=True),
            sa.Column("recovered_at", sa.DateTime, nullable=True),
            sa.Column("root_cause", sa.Text, nullable=True),
            sa.Column("mttr_seconds", sa.Float, nullable=True),
            sa.Column("status", sa.String(20), default="detected", nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )
        op.create_index("idx_session_recovery_auth_id", "session_recovery_audits", ["auth_config_id"])

    # 3. 本地捕获 MVP 审计表
    if not _table("local_capture_audits"):
        op.create_table(
            "local_capture_audits",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("device_id", sa.String(100), nullable=False),
            sa.Column("task_token_hash", sa.String(100), nullable=False),
            sa.Column("origin_url", sa.Text, nullable=False),
            sa.Column("reader_doc_checksum", sa.String(100), nullable=False),
            sa.Column("body_length", sa.Integer, nullable=False, default=0),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )

    # 4. 每日 Canary 验证记录表
    if not _table("daily_canary_runs"):
        op.create_table(
            "daily_canary_runs",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("source_id", UUIDString, sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
            sa.Column("run_date", sa.String(10), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("body_length", sa.Integer, nullable=False, default=0),
            sa.Column("paywall_residual_detected", sa.Boolean, nullable=False, default=False),
            sa.Column("error_message", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )
        op.create_index("idx_daily_canary_source_date", "daily_canary_runs", ["source_id", "run_date"], unique=True)

    # 5. Auth Archive 安全解压审计表
    if not _table("auth_archive_extractions"):
        op.create_table(
            "auth_archive_extractions",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("archive_name", sa.String(255), nullable=False),
            sa.Column("entry_count", sa.Integer, nullable=False, default=0),
            sa.Column("uncompressed_bytes", sa.BigInteger, nullable=False, default=0),
            sa.Column("compression_ratio", sa.Float, nullable=False, default=1.0),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("rejection_reason", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )

    # 6. 一级 Topic 实体表与事件映射关联表
    if not _table("topics"):
        op.create_table(
            "topics",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("creation_type", sa.String(20), nullable=False, default="manual"),
            sa.Column("rule_spec", sa.JSON, nullable=True),
            sa.Column("status", sa.String(20), nullable=False, default="active"),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )

    if not _table("topic_event_associations"):
        op.create_table(
            "topic_event_associations",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("topic_id", UUIDString, sa.ForeignKey("topics.id", ondelete="CASCADE"), nullable=False),
            sa.Column("event_id", sa.String(32), sa.ForeignKey("content_events.event_id", ondelete="CASCADE"), nullable=False),
            sa.Column("associated_at", sa.DateTime, nullable=False),
        )
        op.create_index("idx_topic_event_unique", "topic_event_associations", ["topic_id", "event_id"], unique=True)


    # 7. Brief 快照表 (周报/月报不可变快照)
    if not _table("brief_snapshots"):
        op.create_table(
            "brief_snapshots",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("period_key", sa.String(50), nullable=False),
            sa.Column("brief_type", sa.String(20), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("summary_content", sa.Text, nullable=False),
            sa.Column("lineage_snapshot", sa.JSON, nullable=False),
            sa.Column("modality_status", sa.String(30), nullable=False, default="valid"),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )
        op.create_index("idx_brief_period_type_unique", "brief_snapshots", ["period_key", "brief_type"], unique=True)

    # 8. 事实模态守恒审计表
    if not _table("modality_audit_logs"):
        op.create_table(
            "modality_audit_logs",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("brief_id", UUIDString, sa.ForeignKey("brief_snapshots.id", ondelete="CASCADE"), nullable=False),
            sa.Column("upstream_modality", sa.String(30), nullable=False),
            sa.Column("brief_modality", sa.String(30), nullable=False),
            sa.Column("violation_reason", sa.Text, nullable=True),
            sa.Column("override_by", sa.String(100), nullable=True),
            sa.Column("override_reason", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )


def downgrade() -> None:
    """回滚 M4 数据库变更。"""
    if _table("modality_audit_logs"):
        op.drop_table("modality_audit_logs")
    if _table("brief_snapshots"):
        op.drop_table("brief_snapshots")
    if _table("topic_event_associations"):
        op.drop_table("topic_event_associations")
    if _table("topics"):
        op.drop_table("topics")
    if _table("auth_archive_extractions"):
        op.drop_table("auth_archive_extractions")
    if _table("daily_canary_runs"):
        op.drop_table("daily_canary_runs")
    if _table("local_capture_audits"):
        op.drop_table("local_capture_audits")
    if _table("session_recovery_audits"):
        op.drop_table("session_recovery_audits")
    if _table("paid_source_matrix_audits"):
        op.drop_table("paid_source_matrix_audits")
