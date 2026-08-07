"""WebSub subscription management and unauthenticated hub callbacks."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.domains.fetch.websub import create_subscription, receive_event, verify_subscription
from app.platform.auth import verify_api_key

router = APIRouter()


class CreateWebSubRequest(BaseModel):
    source_id: str
    hub_url: str
    topic_url: str


@router.post("/subscriptions", dependencies=[Depends(verify_api_key)])  # noqa: V103
def api_create_websub(req: CreateWebSubRequest, db: Session = Depends(get_db)):  # noqa: V103
    try:
        row, verify_token, _secret = create_subscription(
            db,
            source_id=req.source_id,
            hub_url=req.hub_url,
            topic_url=req.topic_url,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    return {
        "status": row.status,
        "subscription_id": row.id,
        "callback_path": row.callback_path,
        "verify_token": verify_token,
    }


@router.get("/callback/{subscription_id}", response_class=PlainTextResponse)  # noqa: V103
def api_websub_verify(  # noqa: V103
    subscription_id: str,
    mode: str,
    topic: str,
    challenge: str,
    verify_token: str,
    lease_seconds: int = 86_400,
    db: Session = Depends(get_db),
):
    try:
        verify_subscription(
            db,
            subscription_id=subscription_id,
            mode=mode,
            topic=topic,
            challenge=challenge,
            verify_token=verify_token,
            lease_seconds=lease_seconds,
        )
    except ValueError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    return challenge


@router.post("/callback/{subscription_id}")  # noqa: V103
async def api_websub_callback(subscription_id: str, request: Request, db: Session = Depends(get_db)):  # noqa: V103
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256") or request.headers.get("X-Hub-Signature")
    try:
        return receive_event(db, subscription_id=subscription_id, body=body, signature=signature)
    except ValueError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
