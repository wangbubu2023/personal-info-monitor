from __future__ import annotations

import hashlib
import hmac
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.domains.fetch.connectors import builtin_connectors
from app.domains.fetch.daily_canary import run_daily_paid_source_canaries, source_health_history
from app.domains.fetch.site_rules import RuleDiagnostics, RuleValidationError, builtin_registry, match_rules, validate_rule
from app.domains.fetch.websub import create_subscription, receive_event, verify_subscription
from app.domains.identity.session_service import ensure_user_device, issue_session, revoke_device, rotate_refresh_token
from app.domains.notifications.webhooks import create_webhook_subscription, enqueue_webhook_event
from app.domains.sources.state_service import ensure_source_state, source_state_snapshot
from app.models import FetchJob, IdentitySession, OutboxEvent, Source, SourceHealthSnapshot, WebSubDelivery


@pytest.fixture
def sync_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_site_rule_contract_is_fail_closed_and_deterministic():
    assert builtin_registry.get("example_site_v1", 1) is not None
    match = match_rules("https://www.example.com/article/42", builtin_registry.eligible())
    assert match is not None
    assert match.rule.rule_id == "example_site_v1"
    with pytest.raises(RuleValidationError):
        validate_rule({"schema_version": "site-rule/v1", "rule_id": "unsafe", "revision": 1, "matches": {"hosts": ["example.com"]}, "unknown_capability": True})
    diagnostics = RuleDiagnostics(degrade_after=3)
    diagnostics.record("example_site_v1", success=False)
    diagnostics.record("example_site_v1", success=False)
    health = diagnostics.record("example_site_v1", success=False)
    assert health.status == "degraded"


def test_source_state_split_keeps_legacy_source_compatibility(sync_db: Session):
    source = Source(name="State source", type="rss", url="https://example.com/feed.xml", enabled=True)
    sync_db.add(source)
    sync_db.commit()
    ensure_source_state(sync_db, source)
    snapshot = source_state_snapshot(sync_db, str(source.id))
    assert snapshot["policy"]["enabled"] is True
    assert snapshot["policy"]["fetch_interval"] == 60


def test_identity_refresh_rotation_reuse_and_device_revoke(sync_db: Session):
    user, device = ensure_user_device(sync_db, subject="user-1", tenant_id="tenant-a", device_name="Mac")
    issued = issue_session(sync_db, user_id=user.id, device_id=device.id, scopes=["source:read"])
    rotated = rotate_refresh_token(sync_db, issued["refresh_token"])
    assert rotated["tenant_id"] == "tenant-a"
    with pytest.raises(ValueError, match="reuse detected"):
        rotate_refresh_token(sync_db, issued["refresh_token"])
    # Family-reuse detection already revokes both the original and rotated
    # sessions; device revocation is therefore idempotent and has no active
    # sessions left to change.
    assert revoke_device(sync_db, device_id=device.id, tenant_id="tenant-a") == 0
    assert sync_db.query(IdentitySession).filter(IdentitySession.device_id == device.id, IdentitySession.revoked_at.is_not(None)).count() == 2


def test_websub_verification_signature_replay_and_shared_fetch_job(sync_db: Session):
    source = Source(name="WebSub source", type="rss", url="https://example.com/feed.xml", enabled=True)
    sync_db.add(source)
    sync_db.commit()
    subscription, verify_token, secret = create_subscription(
        sync_db,
        source_id=str(source.id),
        hub_url="https://hub.example.net/",
        topic_url="https://example.com/feed.xml",
    )
    verify_subscription(
        sync_db,
        subscription_id=subscription.id,
        mode="subscribe",
        topic=subscription.topic_url,
        challenge="challenge-1",
        verify_token=verify_token,
    )
    body = b"<rss><channel><item><title>New item</title><link>https://example.com/a</link></item></channel></rss>"
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    accepted = receive_event(sync_db, subscription_id=subscription.id, body=body, signature=signature)
    assert accepted["status"] == "accepted"
    duplicate = receive_event(sync_db, subscription_id=subscription.id, body=body, signature=signature)
    assert duplicate["status"] == "duplicate"
    assert sync_db.query(FetchJob).count() == 1
    assert sync_db.query(WebSubDelivery).count() == 1


def test_webhook_outbox_filters_and_connector_manifest(sync_db: Session):
    row, _secret = create_webhook_subscription(
        sync_db,
        target_url="https://hooks.example.net/pim",
        event_filters=["brief.published"],
    )
    assert row.active is True
    assert builtin_connectors.get("reference.rss") is not None
    assert enqueue_webhook_event(
        sync_db,
        event_type="brief.published",
        aggregate_type="brief",
        aggregate_id=str(uuid.uuid4()),
        payload={"brief_id": "brief-1"},
    ) == 1
    assert sync_db.query(OutboxEvent).filter(OutboxEvent.event_type == "integration.webhook").count() == 1


@pytest.mark.asyncio
async def test_daily_paid_canary_persists_health_history(sync_db: Session):
    source = Source(
        name="Paid canary source",
        type="rss",
        url="https://example.com/paid.xml",
        enabled=True,
        auth_required=True,
    )
    sync_db.add(source)
    sync_db.commit()
    body = "Readable paid article body. " * 8

    def new_session():
        return sessionmaker(bind=sync_db.get_bind())()

    result = await run_daily_paid_source_canaries(
        run_date="2026-08-07",
        probe=lambda _db, _source: {"body": body, "http_status": 200, "metadata": {"probe": "test"}},
        session_factory=new_session,
    )

    assert result == {"attempted": 1, "succeeded": 1, "failed": 0, "source_ids": [str(source.id)]}
    snapshot = sync_db.query(SourceHealthSnapshot).filter(SourceHealthSnapshot.source_id == source.id).one()
    assert snapshot.status == "success"
    assert snapshot.login_required is False
    assert source_health_history(sync_db, str(source.id), days=30)[0]["metadata"] == {"probe": "test"}
