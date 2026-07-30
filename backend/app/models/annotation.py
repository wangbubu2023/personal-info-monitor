"""Immutable human annotation tasks, labels, and adjudications."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class AnnotationTask(Base):
    """Stable review target shared by inline annotation and adjudication."""

    __tablename__ = "annotation_tasks"
    __table_args__ = (
        UniqueConstraint(
            "task_type",
            "target_fingerprint",
            "schema_version",
            name="uq_annotation_task_fingerprint",
        ),
        Index("ix_annotation_tasks_status_type", "status", "task_type"),
        Index("ix_annotation_tasks_target", "target_type", "target_id"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_type = Column(String(48), nullable=False)
    target_type = Column(String(24), nullable=False)
    target_id = Column(String(128), nullable=False)
    secondary_target_id = Column(String(128), nullable=True)
    target_fingerprint = Column(String(64), nullable=False)
    schema_version = Column(String(24), nullable=False, default="v1")
    status = Column(String(24), nullable=False, default="pending")
    priority = Column(Float, nullable=False, default=0.0)
    reason = Column(String(255), nullable=True)
    context_snapshot = Column(JSON, nullable=False, default=dict)
    prediction_snapshot = Column(JSON, nullable=False, default=dict)
    source_dataset = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)

    labels = relationship(
        "AnnotationLabel",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="AnnotationLabel.created_at",
    )
    adjudication = relationship(
        "AnnotationAdjudication",
        back_populates="task",
        cascade="all, delete-orphan",
        uselist=False,
    )


class AnnotationLabel(Base):
    """Append-only human label; corrections point at the superseded label."""

    __tablename__ = "annotation_labels"
    __table_args__ = (Index("ix_annotation_labels_task_created", "task_id", "created_at"),)

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(
        UUIDString,
        ForeignKey("annotation_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    annotator = Column(String(128), nullable=False, default="local-user")
    label_payload = Column(JSON, nullable=False)
    note = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    supersedes_id = Column(
        UUIDString,
        ForeignKey("annotation_labels.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)

    task = relationship("AnnotationTask", back_populates="labels")


class AnnotationAdjudication(Base):
    """Final immutable verdict for a task that required concentrated review."""

    __tablename__ = "annotation_adjudications"
    __table_args__ = (UniqueConstraint("task_id", name="uq_annotation_adjudication_task"),)

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(
        UUIDString,
        ForeignKey("annotation_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    final_payload = Column(JSON, nullable=False)
    adjudicator = Column(String(128), nullable=False, default="local-user")
    rationale = Column(Text, nullable=False)
    gold_candidate = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)

    task = relationship("AnnotationTask", back_populates="adjudication")
