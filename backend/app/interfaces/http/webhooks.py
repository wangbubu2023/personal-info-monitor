"""Authenticated Webhook subscription management API."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.domains.notifications.webhooks import create_webhook_subscription, list_webhooks, set_webhook_active

router = APIRouter()


class CreateWebhookRequest(BaseModel):
    target_url: str
    event_filters: list[str] = Field(default_factory=list, max_length=32)
    secret: str | None = None


class ActiveWebhookRequest(BaseModel):
    active: bool


@router.get("")  # noqa: V103
def api_list_webhooks(db: Session = Depends(get_db)):  # noqa: V103
    return {"items": list_webhooks(db)}


@router.post("")  # noqa: V103
def api_create_webhook(req: CreateWebhookRequest, db: Session = Depends(get_db)):  # noqa: V103
    try:
        row, secret = create_webhook_subscription(
            db,
            target_url=req.target_url,
            event_filters=req.event_filters,
            secret=req.secret,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    return {"status": "created", "id": row.id, "target_url": row.target_url, "secret": secret}


@router.patch("/{subscription_id}")  # noqa: V103
def api_set_webhook_active(subscription_id: str, req: ActiveWebhookRequest, db: Session = Depends(get_db)):  # noqa: V103
    try:
        row = set_webhook_active(db, subscription_id, req.active)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    return {"status": "updated", "id": row.id, "active": row.active}
