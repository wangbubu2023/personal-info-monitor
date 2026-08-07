"""Immutable Weekly/Monthly Brief snapshots and modality audits."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.brief import BriefSnapshot, MODALITY_SCORE_MAP, ModalityAuditLog, ModalityLevel
from app.models.content_event import ContentEventSnapshot
from app.models.topic import TopicEventAssociation
from app.utils.datetime import utcnow_naive


def _modality(value: str) -> ModalityLevel:
    try:
        return ModalityLevel(str(value or "").strip())
    except ValueError as exc:
        allowed = ", ".join(level.value for level in ModalityLevel)
        raise ValueError(f"Unknown modality {value!r}; expected one of: {allowed}") from exc


def validate_modality_lattice(upstream_modality: str, brief_modality: str) -> tuple[bool, str | None]:
    """A downstream Brief may not assert more certainty than its sources."""

    up_enum = _modality(upstream_modality)
    br_enum = _modality(brief_modality)
    up_score = MODALITY_SCORE_MAP[up_enum]
    br_score = MODALITY_SCORE_MAP[br_enum]
    if br_score > up_score:
        return False, (
            f"Modality Inversion Violation: Brief assertion level '{br_enum.value}' "
            f"(score {br_score}) exceeds upstream Level '{up_enum.value}' (score {up_score})."
        )
    return True, None


def _resolve_lineage(db: Session, snapshot_ids: list[str]) -> list[dict]:
    if not snapshot_ids:
        raise ValueError("At least one upstream Event Snapshot is required")
    try:
        normalized_ids = sorted({int(value) for value in snapshot_ids})
    except (TypeError, ValueError) as exc:
        raise ValueError("upstream_event_snapshot_ids must contain integer snapshot IDs") from exc
    rows = (
        db.query(ContentEventSnapshot)
        .filter(ContentEventSnapshot.id.in_(normalized_ids))
        .all()
    )
    by_id = {int(row.id): row for row in rows}
    missing = [value for value in normalized_ids if value not in by_id]
    if missing:
        raise ValueError(f"Upstream Event Snapshot(s) not found: {missing}")
    return [
        {
            "snapshot_id": str(row.id),
            "event_id": row.event_id,
            "snapshot_version": int(row.version),
            "generator_version": row.generator_version,
        }
        for row in (by_id[value] for value in normalized_ids)
    ]


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
    version: int = 1,
    supersedes_brief_id: str | None = None,
) -> tuple[BriefSnapshot, ModalityAuditLog | None]:
    """Publish an immutable Brief, or return the exact prior publication."""

    period = str(period_key or "").strip()
    brief_kind = str(brief_type or "").strip()
    clean_title = str(title or "").strip()
    clean_summary = str(summary_content or "").strip()
    generator = str(generator_version or "").strip()
    if brief_kind not in {"weekly", "monthly"}:
        raise ValueError("brief_type must be either 'weekly' or 'monthly'")
    if not period or not clean_title or not clean_summary or not generator:
        raise ValueError("period_key, title, summary_content, and generator_version are required")
    if int(version) < 1:
        raise ValueError("version must be a positive integer")

    lineage_rows = _resolve_lineage(db, upstream_event_snapshot_ids)
    upstream = _modality(upstream_modality).value
    downstream = _modality(brief_modality).value
    is_valid, violation_msg = validate_modality_lattice(upstream, downstream)
    modality_status = "valid" if is_valid else "violation_flagged"
    violation_count = 0 if is_valid else 1
    publication_status = "published" if is_valid else "blocked"
    lineage = {
        "source_event_snapshots": lineage_rows,
        "source_event_snapshot_ids": [row["snapshot_id"] for row in lineage_rows],
        "input_version": 1,
        "generator_version": generator,
        "period_key": period,
        "upstream_modality": upstream,
        "brief_modality": downstream,
        "checker_version": "modality-lattice-v1",
        "modality_violation_count": violation_count,
        "brief_version": int(version),
        "supersedes_brief_id": supersedes_brief_id,
    }

    existing = (
        db.query(BriefSnapshot)
        .filter(
            BriefSnapshot.period_key == period,
            BriefSnapshot.brief_type == brief_kind,
            BriefSnapshot.version == int(version),
        )
        .first()
    )
    if existing:
        same_publication = (
            existing.title == clean_title
            and existing.summary_content == clean_summary
            and existing.lineage_snapshot == lineage
            and existing.modality_status == modality_status
            and int(existing.modality_violation_count or 0) == violation_count
            and existing.publication_status == publication_status
        )
        if not same_publication:
            raise ValueError(f"Brief {brief_kind}/{period} is already published and immutable")
        audit = (
            db.query(ModalityAuditLog)
            .filter(ModalityAuditLog.brief_id == existing.id)
            .first()
        )
        return existing, audit

    now = utcnow_naive()
    brief = BriefSnapshot(
        id=str(uuid.uuid4()),
        period_key=period,
        brief_type=brief_kind,
        version=int(version),
        title=clean_title,
        summary_content=clean_summary,
        lineage_snapshot=lineage,
        modality_status=modality_status,
        modality_violation_count=violation_count,
        publication_status=publication_status,
        created_at=now,
        updated_at=now,
    )
    db.add(brief)

    audit_log = None
    if not is_valid:
        audit_log = ModalityAuditLog(
            id=str(uuid.uuid4()),
            brief_id=brief.id,
            upstream_modality=upstream,
            brief_modality=downstream,
            violation_reason=violation_msg,
            created_at=now,
        )
        db.add(audit_log)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        concurrent = (
            db.query(BriefSnapshot)
            .filter(BriefSnapshot.period_key == period, BriefSnapshot.brief_type == brief_kind)
            .first()
        )
        if concurrent is None:
            raise
        same_publication = (
            concurrent.title == clean_title
            and concurrent.summary_content == clean_summary
            and concurrent.lineage_snapshot == lineage
            and concurrent.modality_status == modality_status
            and int(concurrent.modality_violation_count or 0) == violation_count
            and concurrent.publication_status == publication_status
        )
        if not same_publication:
            raise ValueError(f"Brief {brief_kind}/{period} is already published and immutable") from exc
        concurrent_audit = (
            db.query(ModalityAuditLog)
            .filter(ModalityAuditLog.brief_id == concurrent.id)
            .first()
        )
        return concurrent, concurrent_audit
    db.refresh(brief)
    if audit_log is not None:
        db.refresh(audit_log)
    return brief, audit_log


def override_brief_modality_violation(
    db: Session,
    brief_id: str,
    override_by: str,
    override_reason: str,
) -> BriefSnapshot:
    """Approve a flagged violation with an attributable reason."""

    actor = str(override_by or "").strip()
    reason = str(override_reason or "").strip()
    if not actor or not reason:
        raise ValueError("override_by and override_reason are required")
    brief = db.query(BriefSnapshot).filter(BriefSnapshot.id == brief_id).first()
    if not brief:
        raise ValueError(f"Brief {brief_id} not found")
    if brief.modality_status != "violation_flagged":
        raise ValueError("Only a violation_flagged Brief may be overridden")
    log = db.query(ModalityAuditLog).filter(ModalityAuditLog.brief_id == brief_id).first()
    if not log or not log.violation_reason:
        raise ValueError("Brief has no modality violation audit to override")

    brief.modality_status = "override_approved"
    brief.publication_status = "published"
    log.override_by = actor
    log.override_reason = reason
    db.commit()
    db.refresh(brief)
    return brief


def brief_to_dict(brief: BriefSnapshot) -> dict:
    return {
        "brief_id": brief.id,
        "period_key": brief.period_key,
        "brief_type": brief.brief_type,
        "version": int(brief.version or 1),
        "title": brief.title,
        "summary_content": brief.summary_content,
        "lineage_snapshot": brief.lineage_snapshot,
        "modality_status": brief.modality_status,
        "modality_violation_count": int(brief.modality_violation_count or 0),
        "publication_status": brief.publication_status,
        "created_at": brief.created_at.isoformat() if brief.created_at else None,
        "updated_at": brief.updated_at.isoformat() if brief.updated_at else None,
    }


def list_briefs(
    db: Session,
    *,
    brief_type: str | None = None,
    period_key: str | None = None,
) -> list[dict]:
    query = db.query(BriefSnapshot)
    if brief_type:
        query = query.filter(BriefSnapshot.brief_type == brief_type)
    if period_key:
        query = query.filter(BriefSnapshot.period_key == period_key)
    return [
        brief_to_dict(item)
        for item in query.order_by(BriefSnapshot.period_key.desc(), BriefSnapshot.version.desc()).all()
    ]


def get_brief(db: Session, brief_id: str) -> BriefSnapshot | None:
    return db.query(BriefSnapshot).filter(BriefSnapshot.id == brief_id).first()


def _period_window(period_key: str, brief_type: str) -> tuple[datetime, datetime]:
    period = str(period_key or "").strip()
    if brief_type == "monthly":
        try:
            start_date = date.fromisoformat(f"{period}-01")
        except ValueError as exc:
            raise ValueError("monthly period_key must be YYYY-MM") from exc
        next_month = date(start_date.year + (start_date.month == 12), 1 if start_date.month == 12 else start_date.month + 1, 1)
        return datetime.combine(start_date, datetime.min.time()), datetime.combine(next_month, datetime.min.time())
    if brief_type == "weekly":
        try:
            year_text, week_text = period.split("-W", 1)
            start_date = date.fromisocalendar(int(year_text), int(week_text), 1)
        except (ValueError, TypeError) as exc:
            raise ValueError("weekly period_key must be YYYY-Www") from exc
        end_date = start_date + timedelta(days=7)
        return datetime.combine(start_date, datetime.min.time()), datetime.combine(end_date, datetime.min.time())
    raise ValueError("brief_type must be either 'weekly' or 'monthly'")


def generate_brief_snapshot(
    db: Session,
    *,
    period_key: str,
    brief_type: str,
    topic_id: str | None = None,
    regenerate: bool = False,
    generator_version: str = "brief-rules-v1",
) -> tuple[BriefSnapshot, ModalityAuditLog | None]:
    """Generate a deterministic Brief from immutable EventSnapshot inputs."""

    start_at, end_at = _period_window(period_key, brief_type)
    query = db.query(ContentEventSnapshot).filter(
        ContentEventSnapshot.created_at >= start_at,
        ContentEventSnapshot.created_at < end_at,
    )
    if topic_id:
        event_ids = [
            row.event_id
            for row in db.query(TopicEventAssociation.event_id)
            .filter(TopicEventAssociation.topic_id == topic_id)
            .all()
        ]
        if not event_ids:
            raise ValueError(f"Topic {topic_id} has no associated events")
        query = query.filter(ContentEventSnapshot.event_id.in_(event_ids))
    snapshots = query.order_by(ContentEventSnapshot.created_at.asc(), ContentEventSnapshot.id.asc()).all()
    if not snapshots:
        raise ValueError(f"No EventSnapshot inputs found for {brief_type}/{period_key}")
    lines = [f"- {item.title}: {(item.summary or item.what_changed or '').strip()}" for item in snapshots]
    title_prefix = "周报" if brief_type == "weekly" else "月报"
    title = f"{title_prefix} {period_key}"
    summary = "\n".join(line[:1_500] for line in lines)[:50_000]
    prior = (
        db.query(BriefSnapshot)
        .filter(BriefSnapshot.period_key == period_key, BriefSnapshot.brief_type == brief_type)
        .order_by(BriefSnapshot.version.desc())
        .first()
    )
    version = int(prior.version or 1) + 1 if regenerate and prior else 1
    supersedes_id = prior.id if regenerate and prior else None
    return create_brief_snapshot(
        db,
        period_key=period_key,
        brief_type=brief_type,
        title=title,
        summary_content=summary,
        upstream_event_snapshot_ids=[str(item.id) for item in snapshots],
        upstream_modality="reported",
        brief_modality="reported",
        generator_version=generator_version,
        version=version,
        supersedes_brief_id=supersedes_id,
    )
