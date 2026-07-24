from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domains.events.engine import assign_content
from app.domains.events.lifecycle import lifecycle_tick
from app.domains.events.operations import merge_events, resolve_event, revert_operation, set_event_lifecycle
from app.domains.events.rebalance import run_rebalance
from app.domains.events.signature import extract_event_signature
from app.domains.events.source_independence import independence_summary, registrable_domain
from app.models import (
    Content,
    ContentEvent,
    ContentEventSnapshot,
    EventAssignmentLog,
    EventMembershipV1,
    EventRebalanceRun,
    EventSignature,
    Source,
)
from app.models.source import SourceType
from app.utils.datetime import utcnow_naive


@pytest.fixture()
def event_session(tmp_path, monkeypatch):
    monkeypatch.setenv("EVENT_V1_ENABLED", "true")
    monkeypatch.setenv("EVENT_V1_ASSIGNMENT", "true")
    engine = create_engine(f"sqlite:///{tmp_path / 'event-v1.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _content(source, *, title, summary="Summary", hour=9, metadata=None):
    return Content(
        source=source,
        title=title,
        summary=summary,
        original_url=f"{source.url.rstrip('/')}/{hour}/{abs(hash(title))}",
        content_type="website",
        publish_time=datetime(2026, 7, 24, hour, 0),
        fetched_at=datetime(2026, 7, 24, hour, 5),
        metadata_=metadata or {},
    )


def test_signature_extracts_hard_fields_modality_and_evidence():
    signature = extract_event_signature(
        title="据报 Acme 计划在新加坡发布 Model v2.4，投入 US$3.5 billion，提升 12%",
        summary="The planned launch is on 2026-07-25.",
        publish_time=datetime(2026, 7, 24),
    )

    assert signature["signature_version"] == "event-signature-v1"
    assert signature["modality"] == "planned"
    assert signature["trigger_action"]["lemma"] in {"launch", "plan"}
    assert {"type": "version", "value": "2.4"} in signature["identifiers"]
    assert any(row["type"] == "money" and row["value"] == "3.5 billion" for row in signature["quantities"])
    assert any(row["type"] == "percent" and row["value"] == "12" for row in signature["quantities"])
    assert signature["location"]["canonical_id"] == "singapore"
    assert signature["event_time_start"] == datetime(2026, 7, 25)
    assert signature["evidence_spans"]


def test_online_assignment_keeps_stable_id_and_rejects_version_conflict(event_session):
    with event_session() as db:
        official = Source(name="Acme Official", type=SourceType.WEBSITE, url="https://news.acme.com")
        media = Source(name="Independent Media", type=SourceType.WEBSITE, url="https://media.example.co.uk")
        first = _content(official, title="Acme confirms launch of Model v2.4 in Singapore")
        followup = _content(media, title="Acme confirms launch of Model v2.4 in Singapore", hour=10)
        different = _content(media, title="Acme confirms launch of Model v3.0 in Singapore", hour=11)
        db.add_all([official, media, first, followup, different])
        db.flush()

        first_result = assign_content(db, str(first.id))
        followup_result = assign_content(db, str(followup.id))
        different_result = assign_content(db, str(different.id))
        db.commit()

        assert first_result.created is True
        assert followup_result.event_id == first_result.event_id
        assert followup_result.created is False
        assert different_result.event_id != first_result.event_id
        assert different_result.decision in {"new", "review_new"}
        conflict_log = (
            db.query(EventAssignmentLog)
            .filter(EventAssignmentLog.content_id == str(different.id))
            .one()
        )
        assert "different_version" in conflict_log.candidates[0]["hard_conflicts"]
        assert db.query(EventSignature).count() == 3
        assert db.query(EventMembershipV1).filter(EventMembershipV1.active.is_(True)).count() == 3
        stable = db.get(ContentEvent, first_result.event_id)
        original_id = stable.event_id
        stable.title = "A completely different display title"
        stable.centroid = {**(stable.centroid or {}), "tokens": ["changed"]}
        db.commit()
        assert db.get(ContentEvent, original_id).event_id == original_id


def test_duplicate_propagation_does_not_create_meaningless_snapshot(event_session):
    with event_session() as db:
        official = Source(name="Official Agency", type=SourceType.WEBSITE, url="https://agency.gov.example")
        reprint = Source(name="Reprint", type=SourceType.RSS, url="https://feed.publisher.example")
        first = _content(
            official,
            title="Official confirms policy Bill AB-123 on 2026-07-24",
            summary="The policy is confirmed.",
            metadata={"source_role": "official", "duplicate_group_id": "dup-1"},
        )
        copy = _content(
            reprint,
            title="Official confirms policy Bill AB-123 on 2026-07-24",
            summary="The policy is confirmed.",
            hour=10,
            metadata={"source_role": "reprint", "duplicate_group_id": "dup-1", "is_reprint": True},
        )
        db.add_all([official, reprint, first, copy])
        db.flush()
        first_result = assign_content(db, str(first.id))
        snapshot_count = db.query(ContentEventSnapshot).filter_by(event_id=first_result.event_id).count()
        copy_result = assign_content(db, str(copy.id))
        db.commit()

        assert copy_result.event_id == first_result.event_id
        assert copy_result.relation == "duplicate"
        assert db.query(ContentEventSnapshot).filter_by(event_id=first_result.event_id).count() == snapshot_count
        event = db.get(ContentEvent, first_result.event_id)
        assert event.latest_snapshot_version == 1
        assert event.independent_source_count == 1


def test_psl_and_origin_groups_do_not_count_reprints_as_independent():
    assert registrable_domain("https://a.b.example.co.uk/story") == "example.co.uk"
    rows = [
        {
            "source_url": "https://wire.example.com",
            "article_url": "https://one.example.com/a",
            "metadata": {"source_role": "wire", "origin_group": "wire-1"},
        },
        {
            "source_url": "https://publisher.example.net",
            "article_url": "https://publisher.example.net/b",
            "metadata": {"source_role": "reprint", "origin_group": "wire-1"},
        },
        {
            "source_url": "https://regulator.gov",
            "article_url": "https://regulator.gov/c",
            "metadata": {"source_role": "official", "origin_group": "regulator"},
        },
    ]
    summary = independence_summary(rows)
    assert summary["material_count"] == 3
    assert summary["origin_group_count"] == 2
    assert summary["effective_independent_source_weight"] == 2.0
    assert summary["effective_independent_source_count"] == 2


def test_lifecycle_merge_redirect_and_bounded_rebalance(event_session):
    with event_session() as db:
        source = Source(name="News", type=SourceType.WEBSITE, url="https://news.example.com")
        first = _content(source, title="Acme confirms launch Model v2.4 in Singapore")
        second = _content(source, title="Acme confirms launch Model v2.5 in Singapore", hour=10)
        db.add_all([source, first, second])
        db.flush()
        first_result = assign_content(db, str(first.id))
        second_result = assign_content(db, str(second.id))
        db.flush()
        first_event = db.get(ContentEvent, first_result.event_id)
        first_event.last_material_update_at = utcnow_naive() - timedelta(days=20)
        changed = lifecycle_tick(db)
        assert changed["active_to_cooling"] >= 1
        first_event.last_material_update_at = utcnow_naive() - timedelta(days=40)
        changed = lifecycle_tick(db)
        assert changed["cooling_to_closed"] >= 1

        set_event_lifecycle(
            db,
            first_event.event_id,
            action="reopen",
            actor="tester",
            reason="explicit follow-up",
        )
        assert first_event.status == "reopened"
        merge = merge_events(
            db,
            canonical_event_id=second_result.event_id,
            source_event_ids=[first_result.event_id],
            actor="tester",
            reason="manual adjudication",
        )
        db.flush()
        assert merge.operation_type == "merge"
        assert resolve_event(db, first_result.event_id)["event_id"] == second_result.event_id
        reverted = revert_operation(
            db,
            str(merge.id),
            actor="tester",
            reason="rollback drill",
        )
        db.flush()
        assert reverted.operation_type == "revert"
        assert resolve_event(db, first_result.event_id)["event_id"] == first_result.event_id

        for index in range(25):
            db.add(
                ContentEvent(
                    event_id=f"closed-{index:025d}",
                    event_key=f"closed-key-{index}",
                    title=f"Closed {index}",
                    status="closed",
                    cluster_version="event-v1.0-rules",
                    last_material_update_at=utcnow_naive(),
                    centroid={"tokens": ["common"], "signature": {}},
                    created_at=utcnow_naive(),
                    updated_at=utcnow_naive(),
                )
            )
        result = run_rebalance(
            db,
            run_kind="deep",
            max_events=10,
            max_pairs=1,
            max_runtime_seconds=1,
            checkpoint_size=1,
        )
        db.commit()
        assert result["filtered_closed_count"] >= 25
        assert result["candidate_pair_count"] <= 1
        assert result["closed_pair_comparisons"] == 0
        assert db.query(EventRebalanceRun).count() == 1


@pytest.mark.asyncio
async def test_v1_today_read_uses_same_canonical_snapshot(client, db_session, monkeypatch):
    monkeypatch.setenv("EVENT_V1_ENABLED", "true")
    monkeypatch.setenv("EVENT_V1_TODAY_READ", "true")
    monkeypatch.setenv("EVENT_V1_READ_GATE_APPROVED", "true")
    event = ContentEvent(
        event_id="019f92aeb2d276b09f65b25b239e0ca3",
        event_key="evt-canonical",
        title="Mutable row title",
        summary="Mutable row summary",
        status="active",
        cluster_version="event-v1.0-rules",
        latest_snapshot_version=3,
        event_state="need_to_know",
        independent_source_count=2,
        source_names=["Official", "Independent"],
        last_material_update_at=datetime(2026, 7, 24, 9, 0),
        created_at=datetime(2026, 7, 24, 8, 0),
        updated_at=datetime(2026, 7, 24, 9, 0),
    )
    snapshot = ContentEventSnapshot(
        event_id=event.event_id,
        version=3,
        title="Canonical snapshot title",
        summary="Canonical snapshot conclusion",
        what_changed="confirmed",
        why_matters="important",
        change_type="confirmed_fact",
        change_fingerprint="f" * 64,
        facts=[{"kind": "modality", "value": "confirmed"}],
        evidence_refs=[],
        uncertainty=[],
        source_content_ids=[],
        explanation={"selection_reason": "official plus independent confirmation"},
        created_at=datetime(2026, 7, 24, 9, 0),
    )
    db_session.add_all([event, snapshot])
    await db_session.commit()

    today = await client.get("/api/events/today-highlights", params={"date": "2026-07-24"})
    detail = await client.get(f"/api/events/{event.event_id}")
    config = await client.get("/api/events/config")

    assert today.status_code == 200
    assert today.json()["items"][0]["title"] == "Canonical snapshot title"
    assert today.json()["items"][0]["snapshot_version"] == 3
    assert detail.status_code == 200
    assert detail.json()["snapshots"][0]["version"] == 3
    assert detail.json()["snapshots"][0]["change_type"] == "confirmed_fact"
    assert config.status_code == 200
    assert config.json()["flags"]["EVENT_V1_TODAY_READ"] is True
