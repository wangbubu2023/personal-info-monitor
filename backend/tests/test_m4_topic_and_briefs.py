import uuid
import pytest
from sqlalchemy import create_engine

from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.domains.enrich.brief_service import create_brief_snapshot, override_brief_modality_violation, validate_modality_lattice
from app.domains.events.presentation import export_event_to_markdown, format_event_presentation
from app.domains.events.topic_service import associate_events_to_topic, create_topic, get_topic_details_with_coverage
from app.models.content_event import ContentEvent


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
    for i in range(4):
        event = ContentEvent(
            event_id=f"evt-{uuid.uuid4().hex[:16]}",
            event_key=f"key-{i}-{uuid.uuid4().hex[:8]}",
            title=f"Sample Event {i + 1}",
            summary=f"Event summary content {i + 1}",
            status="active",
        )
        sync_db.add(event)
        events.append(event)
    sync_db.commit()
    return events


def test_m4_06_topic_creation_and_event_identity_preservation(sync_db: Session, sample_events: list[ContentEvent]):
    # 1. 创建 Topic
    topic = create_topic(sync_db, title="AI Chip Supply Chain", description="Tracking NVIDIA & TSMC", creation_type="rule")
    assert topic.id is not None
    assert topic.title == "AI Chip Supply Chain"

    # 2. 关联 Events (绝不破坏 ContentEvent.event_id 原有 ID)
    event_ids = [e.event_id for e in sample_events]
    assocs = associate_events_to_topic(sync_db, topic.id, event_ids)
    assert len(assocs) == 4

    # 重新查询 ContentEvent，验证 UUID 未被重构或设为 NULL
    for orig_id in event_ids:
        evt = sync_db.query(ContentEvent).filter(ContentEvent.event_id == orig_id).first()
        assert evt is not None
        assert evt.event_id == orig_id

    # 3. 查看 Topic 详情与来源覆盖率
    details = get_topic_details_with_coverage(sync_db, topic.id)
    assert details["topic_id"] == topic.id
    assert details["event_count"] == 4
    assert len(details["timeline"]) == 4


def test_m4_07_m4_08_brief_lineage_and_modality_lattice(sync_db: Session):
    period_key = "2026-W30"
    snapshot_ids = ["snap-1", "snap-2"]

    # 1. 模态守恒验证: 上游 confirmed >= 下游 reported -> 合规
    is_valid, err = validate_modality_lattice(upstream_modality="confirmed", brief_modality="reported")
    assert is_valid is True
    assert err is None

    brief, audit = create_brief_snapshot(
        sync_db,
        period_key=period_key,
        brief_type="weekly",
        title="Weekly Tech Digest W30",
        summary_content="Everything confirmed by primary sources.",
        upstream_event_snapshot_ids=snapshot_ids,
        upstream_modality="confirmed",
        brief_modality="reported",
    )
    assert brief.modality_status == "valid"
    assert audit is None

    # 2. 模态倒置违规: 上游 alleged < 下游 confirmed -> 触发违规标记
    period_key_monthly = "2026-07"
    brief_v, audit_v = create_brief_snapshot(
        sync_db,
        period_key=period_key_monthly,
        brief_type="monthly",
        title="July Monthly Brief",
        summary_content="Over-confident summary.",
        upstream_event_snapshot_ids=snapshot_ids,
        upstream_modality="alleged",  # 上游仅为传闻
        brief_modality="confirmed", # 下游断言为确认 (Modality Inversion!)
    )
    assert brief_v.modality_status == "violation_flagged"
    assert audit_v is not None
    assert "Modality Inversion Violation" in audit_v.violation_reason

    # 3. 人工 Override 解除违规警告
    overridden = override_brief_modality_violation(
        sync_db,
        brief_id=brief_v.id,
        override_by="Sheldon",
        override_reason="Cross-verified with SEC filing manually.",
    )
    assert overridden.modality_status == "override_approved"




def test_m4_09_curated_full_presentation_and_export_filter():
    event_data = {
        "id": "evt-123",
        "title": "【独家】NVIDIA Launching Next-Gen GPU Architecture",
        "summary": "Key highlights of the announcement.",
        "reports": [{"id": f"rep-{i}"} for i in range(10)],
    }

    # 1. 默认 Curated 视图 (仅返回 3 条 Highlights)
    curated = format_event_presentation(event_data=event_data, full_reports=False)
    assert curated["view_mode"] == "curated"
    assert len(curated["timeline"]) == 3

    # 2. 显式 full_reports=True 返回完整 Timeline
    full_view = format_event_presentation(event_data=event_data, full_reports=True)
    assert full_view["view_mode"] == "full"
    assert len(full_view["timeline"]) == 10

    # 3. Markdown 导出付费全文过滤门禁
    md_paid = export_event_to_markdown(
        title="WSJ Paid Article",
        summary="Summary of paywalled text.",
        source_url="https://wsj.com/article/1",
        full_body="SECRET_PAYWALLED_FULL_BODY_TEXT",
        is_paid_source=True,
    )
    assert "SECRET_PAYWALLED_FULL_BODY_TEXT" not in md_paid
    assert "自动过滤付费全文" in md_paid
