"""First-class Topic service that never rewrites Event identity."""

from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.content_event import ContentEvent
from app.models.topic import Topic, TopicEventAssociation
from app.utils.datetime import utcnow_naive

_VALID_CREATION_TYPES = {"rule", "entity", "manual"}


def create_topic(
    db: Session,
    title: str,
    description: str | None = None,
    creation_type: str = "manual",
    rule_spec: dict | None = None,
) -> Topic:
    clean_title = str(title or "").strip()
    kind = str(creation_type or "").strip()
    if not clean_title:
        raise ValueError("Topic title is required")
    if kind not in _VALID_CREATION_TYPES:
        raise ValueError(f"creation_type must be one of {sorted(_VALID_CREATION_TYPES)}")
    if kind in {"rule", "entity"} and not isinstance(rule_spec, dict):
        raise ValueError(f"rule_spec is required for creation_type={kind}")

    now = utcnow_naive()
    topic = Topic(
        id=str(uuid.uuid4()),
        title=clean_title,
        description=(str(description).strip() if description is not None else None),
        creation_type=kind,
        rule_spec=rule_spec or {},
        status="active",
        created_at=now,
        updated_at=now,
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
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        raise ValueError(f"Topic {topic_id} not found")

    normalized_ids = list(dict.fromkeys(str(value or "").strip() for value in event_ids))
    normalized_ids = [value for value in normalized_ids if value]
    if not normalized_ids:
        raise ValueError("At least one event_id is required")
    existing_events = db.query(ContentEvent.event_id).filter(ContentEvent.event_id.in_(normalized_ids)).all()
    existing_ids = {row[0] for row in existing_events}
    missing = [value for value in normalized_ids if value not in existing_ids]
    if missing:
        raise ValueError(f"Event(s) not found: {missing}")

    existing_associations = {
        row.event_id
        for row in db.query(TopicEventAssociation)
        .filter(
            TopicEventAssociation.topic_id == topic_id,
            TopicEventAssociation.event_id.in_(normalized_ids),
        )
        .all()
    }
    now = utcnow_naive()
    associations: list[TopicEventAssociation] = []
    for event_id in normalized_ids:
        if event_id in existing_associations:
            continue
        association = TopicEventAssociation(
            id=str(uuid.uuid4()),
            topic_id=topic_id,
            event_id=event_id,
            associated_at=now,
        )
        try:
            with db.begin_nested():
                db.add(association)
                db.flush()
        except IntegrityError:
            # A concurrent request won the unique (topic_id, event_id) race.
            continue
        associations.append(association)
    db.commit()
    return associations


def get_topic_details_with_coverage(db: Session, topic_id: str) -> dict:
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        return {}
    assocs = db.query(TopicEventAssociation).filter(TopicEventAssociation.topic_id == topic_id).all()
    event_ids = [association.event_id for association in assocs]
    events = db.query(ContentEvent).filter(ContentEvent.event_id.in_(event_ids)).all() if event_ids else []

    source_names = {
        str(source_name).strip()
        for event in events
        for source_name in (event.source_names or [])
        if str(source_name).strip()
    }
    event_timeline = [
        {
            "event_id": event.event_id,
            "title": event.title,
            "summary": event.summary,
            "status": event.status,
            "created_at": event.first_seen_at.isoformat() if event.first_seen_at else None,
            "updated_at": event.last_seen_at.isoformat() if event.last_seen_at else None,
        }
        for event in sorted(events, key=lambda item: item.first_seen_at or datetime.min, reverse=True)
    ]
    return {
        "topic_id": topic.id,
        "title": topic.title,
        "description": topic.description,
        "creation_type": topic.creation_type,
        "rule_spec": topic.rule_spec,
        "status": topic.status,
        "event_count": len(events),
        "unique_source_count": len(source_names),
        "source_coverage": sorted(source_names),
        "timeline": event_timeline,
        "created_at": topic.created_at.isoformat() if topic.created_at else None,
    }
