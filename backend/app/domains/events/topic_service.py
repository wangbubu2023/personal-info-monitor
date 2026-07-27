"""Topic domain service.

Guarantees:
1. Provides first-class Topic entity and API endpoints.
2. Supports creation via explicit rule, entity query, or manual confirmation.
3. Maps ContentEvents via association table without EVER altering underlying Event IDs.
4. Computes Event timeline & source coverage transparently.
"""

from datetime import datetime
import uuid

from sqlalchemy.orm import Session

from app.models.content_event import ContentEvent
from app.models.topic import Topic, TopicEventAssociation
from app.utils.datetime import utcnow_naive


def create_topic(
    db: Session,
    title: str,
    description: str | None = None,
    creation_type: str = "manual",
    rule_spec: dict | None = None,
) -> Topic:
    """创建一级 Topic 实体。"""
    topic = Topic(
        id=str(uuid.uuid4()),
        title=title,
        description=description,
        creation_type=creation_type,
        rule_spec=rule_spec or {},
        status="active",
        created_at=utcnow_naive(),
        updated_at=utcnow_naive(),
    )
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return topic


def associate_events_to_topic(
    db: Session,
    topic_id: str,
    event_ids: list[str],
) -> list[TopicEventAssociation]:
    """关联 ContentEvents 到 Topic，绝不改变 ContentEvent 原有的 UUIDv7 ID。"""
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        raise ValueError(f"Topic {topic_id} not found.")

    associations = []
    now = utcnow_naive()

    for event_id in event_ids:
        # 检查是否已存在关联
        existing = (
            db.query(TopicEventAssociation)
            .filter(
                TopicEventAssociation.topic_id == topic_id,
                TopicEventAssociation.event_id == event_id,
            )
            .first()
        )
        if not existing:
            assoc = TopicEventAssociation(
                id=str(uuid.uuid4()),
                topic_id=topic_id,
                event_id=event_id,
                associated_at=now,
            )
            db.add(assoc)
            associations.append(assoc)

    db.commit()
    return associations


def get_topic_details_with_coverage(
    db: Session,
    topic_id: str,
) -> dict:
    """获取 Topic 及其关联的 ContentEvents、时间线与来源覆盖率。"""
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        return {}

    assocs = (
        db.query(TopicEventAssociation)
        .filter(TopicEventAssociation.topic_id == topic_id)
        .all()
    )
    event_ids = [a.event_id for a in assocs]

    events = db.query(ContentEvent).filter(ContentEvent.event_id.in_(event_ids)).all() if event_ids else []

    # 统计来源覆盖率 (Source coverage)
    source_ids = set()
    for e in events:
        if e.canonical_content_id:
            source_ids.add(e.canonical_content_id)

    event_timeline = [
        {
            "event_id": e.event_id,
            "title": e.title,
            "summary": e.summary,
            "status": e.status,
            "created_at": e.first_seen_at.isoformat() if e.first_seen_at else None,
            "updated_at": e.last_seen_at.isoformat() if e.last_seen_at else None,
        }
        for e in sorted(events, key=lambda x: x.first_seen_at or datetime.min, reverse=True)
    ]

    return {
        "topic_id": topic.id,
        "title": topic.title,
        "description": topic.description,
        "creation_type": topic.creation_type,
        "rule_spec": topic.rule_spec,
        "status": topic.status,
        "event_count": len(events),
        "unique_source_count": len(source_ids),
        "timeline": event_timeline,
        "created_at": topic.created_at.isoformat() if topic.created_at else None,
    }
