"""Canonical persistence behavior shared by SQLite and PostgreSQL."""

from __future__ import annotations

from datetime import timedelta
import os
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models.reliable_execution import OutboxEvent, SchedulerRun
from app.utils.datetime import utcnow_naive


def _urls(tmp_path):
    yield "sqlite", f"sqlite:///{tmp_path / 'contract.db'}"
    postgres = os.getenv("PIM_TEST_POSTGRES_URL", "").strip()
    if postgres:
        yield "postgresql", postgres


@pytest.mark.parametrize("dialect_index", [0, 1])
def test_canonical_unique_rollback_cas_json_time_and_cursor(tmp_path, dialect_index):
    urls = list(_urls(tmp_path))
    if dialect_index >= len(urls):
        pytest.skip("PIM_TEST_POSTGRES_URL is not configured")
    dialect, url = urls[dialect_index]
    engine = create_engine(url)
    SchedulerRun.__table__.drop(engine, checkfirst=True)
    OutboxEvent.__table__.drop(engine, checkfirst=True)
    SchedulerRun.__table__.create(engine)
    OutboxEvent.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    now = utcnow_naive().replace(microsecond=0)

    try:
        with factory() as db:
            first = SchedulerRun(
                schedule_id="digest",
                business_run_key="2026-07-23",
                scheduled_for=now,
                state="pending",
                policy_version="v1",
            )
            db.add(first)
            db.commit()
            first_id = first.id

        with factory() as db:
            db.add(
                SchedulerRun(
                    schedule_id="digest",
                    business_run_key="2026-07-23",
                    scheduled_for=now,
                    state="pending",
                    policy_version="v1",
                )
            )
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
            assert db.query(SchedulerRun).count() == 1

        with factory() as db:
            changed = db.query(SchedulerRun).filter(
                SchedulerRun.id == first_id,
                SchedulerRun.state == "pending",
            ).update({"state": "running"}, synchronize_session=False)
            db.commit()
            assert changed == 1
            stale = db.query(SchedulerRun).filter(
                SchedulerRun.id == first_id,
                SchedulerRun.state == "pending",
            ).update({"state": "failed"}, synchronize_session=False)
            db.commit()
            assert stale == 0

        with factory() as db:
            for index in range(5):
                db.add(
                    OutboxEvent(
                        id=str(uuid.uuid4()),
                        event_type="contract",
                        aggregate_type="test",
                        aggregate_id=str(index),
                        payload_schema_version=1,
                        payload={"index": index, "nullable": None},
                        idempotency_key=f"contract:{dialect}:{index}",
                        state="pending",
                        available_at=now + timedelta(seconds=index),
                    )
                )
            db.commit()

        with factory() as db:
            page1 = db.query(OutboxEvent).order_by(
                OutboxEvent.available_at.asc(), OutboxEvent.id.asc()
            ).limit(2).all()
            cursor = (page1[-1].available_at, page1[-1].id)
            page2 = db.query(OutboxEvent).filter(
                (OutboxEvent.available_at > cursor[0])
                | (
                    (OutboxEvent.available_at == cursor[0])
                    & (OutboxEvent.id > cursor[1])
                )
            ).order_by(OutboxEvent.available_at.asc(), OutboxEvent.id.asc()).limit(2).all()
            assert [row.payload["index"] for row in page1] == [0, 1]
            assert [row.payload["index"] for row in page2] == [2, 3]
            assert page1[0].payload["nullable"] is None
    finally:
        SchedulerRun.__table__.drop(engine, checkfirst=True)
        OutboxEvent.__table__.drop(engine, checkfirst=True)
        engine.dispose()
