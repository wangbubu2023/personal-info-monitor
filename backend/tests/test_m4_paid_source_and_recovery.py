import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.auth_config import AuthConfig, AuthType
from app.models.source import Source
from app.domains.fetch.paid_matrix import (
    ack_session_recovery,
    check_readability,
    complete_session_recovery,
    record_paid_source_result,
    run_daily_canary_for_source,
    trigger_session_expiration,
)


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
def sample_source(sync_db: Session) -> Source:
    source = Source(
        id=str(uuid.uuid4()),
        name="WSJ Premium",
        url="https://www.wsj.com",
        type="website",
    )
    sync_db.add(source)
    sync_db.commit()
    return source


@pytest.fixture
def sample_auth_config(sync_db: Session) -> AuthConfig:
    auth = AuthConfig(
        id=str(uuid.uuid4()),
        name="WSJ Cookie Session",
        site_url="https://www.wsj.com",
        auth_type=AuthType.COOKIE,
    )
    sync_db.add(auth)
    sync_db.commit()
    return auth


def test_m4_01_paid_source_readability_validation(sync_db: Session, sample_source: Source):
    # 1. 简短无读正文 (HTTP 200 但可读性失败)
    short_body = "Too short"
    is_readable, reason = check_readability(short_body)
    assert is_readable is False
    assert reason == "BODY_TOO_SHORT"

    audit1 = record_paid_source_result(sync_db, sample_source.id, short_body)
    assert audit1.last_readable_success_at is None
    assert audit1.failure_code == "BODY_TOO_SHORT"
    assert audit1.recovery_action == "CHECK_SELECTOR_OR_PARSER"

    # 2. Paywall 残留词发现
    paywall_body = "This is a long article text. Subscribe to read full article right now! " * 5
    is_readable, reason = check_readability(paywall_body)
    assert is_readable is False
    assert reason == "PAYWALL_RESIDUAL_DETECTED"

    audit2 = record_paid_source_result(sync_db, sample_source.id, paywall_body)
    assert audit2.failure_code == "PAYWALL_RESIDUAL_DETECTED"
    assert audit2.recovery_action == "RE_AUTHENTICATE_COOKIE"

    # 3. 正常长正文 (成功以可读正文为准)
    valid_body = "WSJ Exclusive Report: Tech sector sees record expansion this quarter. " * 10
    is_readable, reason = check_readability(valid_body)
    assert is_readable is True
    assert reason is None

    audit3 = record_paid_source_result(sync_db, sample_source.id, valid_body)
    assert audit3.last_readable_success_at is not None
    assert audit3.failure_code is None


def test_m4_02_session_recovery_drill_and_mttr(sync_db: Session, sample_auth_config: AuthConfig):
    # 主动触发会话失效演练
    audit = trigger_session_expiration(sync_db, sample_auth_config.id, root_cause="CANARY_FAILURE_SIMULATION")
    assert audit.status == "detected"
    assert audit.detected_at is not None
    assert audit.acked_at is None

    # Ack 确认
    acked = ack_session_recovery(sync_db, audit.id)
    assert acked is not None
    assert acked.status == "acked"
    assert acked.acked_at is not None

    # Recover 完成恢复
    recovered = complete_session_recovery(sync_db, audit.id)
    assert recovered is not None
    assert recovered.status == "recovered"
    assert recovered.recovered_at is not None
    assert recovered.mttr_seconds is not None
    assert recovered.mttr_seconds >= 0.0


def test_m4_04_daily_canary_probe(sync_db: Session, sample_source: Source):
    valid_body = "Daily Canary article sample for verification. " * 10
    canary = run_daily_canary_for_source(sync_db, sample_source.id, valid_body, run_date_str="2026-07-24")

    assert canary.source_id == sample_source.id
    assert canary.run_date == "2026-07-24"
    assert canary.status == "success"
    assert canary.paywall_residual_detected is False
