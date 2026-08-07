"""Topics HTTP handlers."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.domains.events.topic_service import (
    archive_topic,
    associate_events_to_topic,
    create_topic,
    get_topic_details_with_coverage,
    list_topics,
    update_topic,
)

router = APIRouter()


class CreateTopicRequest(BaseModel):
    title: str
    description: str | None = None
    creation_type: str = "manual"
    rule_spec: dict | None = None


class AssociateEventsRequest(BaseModel):
    event_ids: list[str]


class UpdateTopicRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    creation_type: str | None = None
    rule_spec: dict | None = None
    status: str | None = None


@router.get("")
def api_list_topics(
    status: str | None = "active",
    creation_type: str | None = None,
    query: str | None = None,
    db: Session = Depends(get_db),
):
    try:
        return {"items": list_topics(db, status=status, creation_type=creation_type, query=query)}
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err


@router.post("")
def api_create_topic(req: CreateTopicRequest, db: Session = Depends(get_db)):
    try:
        topic = create_topic(
            db,
            title=req.title,
            description=req.description,
            creation_type=req.creation_type,
            rule_spec=req.rule_spec,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    return {"status": "created", "topic_id": topic.id, "title": topic.title}


@router.post("/{topic_id}/events")
def api_associate_events(topic_id: str, req: AssociateEventsRequest, db: Session = Depends(get_db)):
    try:
        assocs = associate_events_to_topic(db, topic_id=topic_id, event_ids=req.event_ids)
        return {"status": "associated", "topic_id": topic_id, "associated_count": len(assocs)}
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err


@router.patch("/{topic_id}")
def api_update_topic(topic_id: str, req: UpdateTopicRequest, db: Session = Depends(get_db)):
    try:
        topic = update_topic(db, topic_id, **req.model_dump(exclude_unset=True))
        return {"status": "updated", "topic": get_topic_details_with_coverage(db, topic_id=topic.id)}
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err


@router.delete("/{topic_id}")
def api_archive_topic(topic_id: str, db: Session = Depends(get_db)):
    try:
        topic = archive_topic(db, topic_id)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    return {"status": "archived", "topic_id": topic.id}


@router.get("/{topic_id}")
def api_get_topic_details(topic_id: str, db: Session = Depends(get_db)):
    details = get_topic_details_with_coverage(db, topic_id=topic_id)
    if not details:
        raise HTTPException(status_code=404, detail="Topic not found")
    return details
