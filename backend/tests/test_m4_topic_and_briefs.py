from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.domains.enrich.brief_service import (
    create_brief_snapshot,
    override_brief_modality_violation,
    validate_modality_lattice,
)
from app.domains.events.presentation import export_event_to_markdown, format_event_presentation
from app.domains.events.topic_service import associate_events_to_topic, create_topic, get_topic_details_with_coverage
from app.models.content_event import ContentEvent, ContentEventSnapshot


@pytest.fixture
def sync_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_events(sync_db: Session) -> list[ContentEvent]:
    events = []
    for index in range(4):
        event = ContentEvent(
            event_id=f"evt-{uuid.uuid4().hex[:16]}",
            event_key=f"key-{index}-{uuid.uuid4().hex[:8]}",
            title=f"Sample Event {index + 1}",
            summary=f"Event summary content {index + 1}",
            status="active",
            source_names=[f"Source {index % 2}", "Wire Service"],
        )
        sync_db.add(event)
        events.append(event)
    sync_db.commit()
    return events


def _snapshots(sync_db: Session, events: list[ContentEvent]) -> list[ContentEventSnapshot]:
    rows = [
        ContentEventSnapshot(
            event_id=event.event_id,
            version=1,
            title=event.title,
            summary=event.summary,
            generator_version="snapshot-rules-v1",
        )
        for event in events[:2]
    ]
    sync_db.add_all(rows)
    sync_db.commit()
    return rows


def test_m4_06_topic_creation_and_event_identity_preservation(sync_db: Session, sample_events: list[ContentEvent]):
    topic = create_topic(
        sync_db,
        title="AI Chip Supply Chain",
        description="Tracking NVIDIA & TSMC",
        creation_type="rule",
        rule_spec={"keywords": ["NVIDIA", "TSMC"]},
    )
    event_ids = [event.event_id for event in sample_events]
    associations = associate_events_to_topic(sync_db, topic.id, event_ids)
    assert len(associations) == 4
    assert associate_events_to_topic(sync_db, topic.id, event_ids) == []

    for original_id in event_ids:
        assert sync_db.get(ContentEvent, original_id).event_id == original_id

    details = get_topic_details_with_coverage(sync_db, topic.id)
    assert details["event_count"] == 4
    assert details["unique_source_count"] == 3
    assert details["source_coverage"] == ["Source 0", "Source 1", "Wire Service"]

    with pytest.raises(ValueError, match="not found"):
        associate_events_to_topic(sync_db, topic.id, ["missing-event"])
    assert sync_db.query(type(associations[0])).count() == 4


def test_m4_07_m4_08_brief_lineage_immutability_and_modality(sync_db: Session, sample_events):
    snapshots = _snapshots(sync_db, sample_events)
    snapshot_ids = [str(row.id) for row in snapshots]

    is_valid, error = validate_modality_lattice("confirmed", "reported")
    assert is_valid is True and error is None
    with pytest.raises(ValueError, match="Unknown modality"):
        validate_modality_lattice("invented", "reported")

    brief, audit = create_brief_snapshot(
        sync_db,
        period_key="2026-W30",
        brief_type="weekly",
        title="Weekly Tech Digest W30",
        summary_content="Everything confirmed by primary sources.",
        upstream_event_snapshot_ids=snapshot_ids,
        upstream_modality="confirmed",
        brief_modality="reported",
    )
    assert brief.modality_status == "valid"
    assert brief.modality_violation_count == 0
    assert brief.publication_status == "published"
    assert audit is None
    assert brief.lineage_snapshot["source_event_snapshots"][0]["event_id"] == sample_events[0].event_id

    repeated, repeated_audit = create_brief_snapshot(
        sync_db,
        period_key="2026-W30",
        brief_type="weekly",
        title="Weekly Tech Digest W30",
        summary_content="Everything confirmed by primary sources.",
        upstream_event_snapshot_ids=snapshot_ids,
        upstream_modality="confirmed",
        brief_modality="reported",
    )
    assert repeated.id == brief.id and repeated_audit is None
    with pytest.raises(ValueError, match="already published and immutable"):
        create_brief_snapshot(
            sync_db,
            period_key="2026-W30",
            brief_type="weekly",
            title="Changed after publication",
            summary_content="Everything confirmed by primary sources.",
            upstream_event_snapshot_ids=snapshot_ids,
            upstream_modality="confirmed",
            brief_modality="reported",
        )
    with pytest.raises(ValueError, match="not found"):
        create_brief_snapshot(
            sync_db,
            period_key="2026-W31",
            brief_type="weekly",
            title="Invalid lineage",
            summary_content="Missing source snapshot.",
            upstream_event_snapshot_ids=["999999"],
        )

    violating, violation_audit = create_brief_snapshot(
        sync_db,
        period_key="2026-07",
        brief_type="monthly",
        title="July Monthly Brief",
        summary_content="Over-confident summary.",
        upstream_event_snapshot_ids=snapshot_ids,
        upstream_modality="alleged",
        brief_modality="confirmed",
    )
    assert violating.modality_status == "violation_flagged"
    assert violating.modality_violation_count == 1
    assert violating.publication_status == "blocked"
    assert violation_audit and "Modality Inversion Violation" in violation_audit.violation_reason
    with pytest.raises(ValueError, match="required"):
        override_brief_modality_violation(sync_db, violating.id, "", "")
    overridden = override_brief_modality_violation(
        sync_db,
        brief_id=violating.id,
        override_by="reviewer",
        override_reason="Cross-verified against the source filing.",
    )
    assert overridden.modality_status == "override_approved"
    assert overridden.publication_status == "published"


def test_m4_09_presentation_helpers_do_not_prove_api_wiring():
    event_data = {
        "id": "evt-123",
        "title": "【独家】NVIDIA Launching Next-Gen GPU Architecture",
        "summary": "Key highlights of the announcement.",
        "reports": [{"id": f"rep-{index}"} for index in range(10)],
    }
    assert len(format_event_presentation(event_data=event_data, full_reports=False)["timeline"]) == 3
    assert len(format_event_presentation(event_data=event_data, full_reports=True)["timeline"]) == 10

    markdown = export_event_to_markdown(
        title="WSJ Paid Article",
        summary="Summary of paywalled text.",
        source_url="https://wsj.com/article/1",
        full_body="SECRET_PAYWALLED_FULL_BODY_TEXT",
        is_paid_source=True,
    )
    assert "SECRET_PAYWALLED_FULL_BODY_TEXT" not in markdown
