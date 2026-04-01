"""Database-backed runtime locks for cross-process fetch coordination."""

from __future__ import annotations

import os
import secrets
from datetime import timedelta

from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.runtime_lock import RuntimeLock
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger

logger = get_logger(__name__)


class RuntimeLockService:
    """Acquire/release lock keys using SQLite rows.

    This service is sync-friendly so it can run inside existing thread-based
    fetch workers.
    """

    def __init__(self) -> None:
        self.owner_id = f"{os.getpid()}-{secrets.token_hex(8)}"

    def acquire(self, key: str, ttl_seconds: int) -> bool:
        now = utcnow_naive()
        expires_at = now + timedelta(seconds=max(1, int(ttl_seconds)))

        with SessionLocal() as db:
            try:
                db.add(RuntimeLock(lock_key=key, owner_id=self.owner_id, expires_at=expires_at))
                db.commit()
                return True
            except IntegrityError:
                db.rollback()

            updated = (
                db.query(RuntimeLock)
                .filter(RuntimeLock.lock_key == key, RuntimeLock.expires_at <= now)
                .update(
                    {
                        RuntimeLock.owner_id: self.owner_id,
                        RuntimeLock.expires_at: expires_at,
                    },
                    synchronize_session=False,
                )
            )
            db.commit()
            return bool(updated)

    def release(self, key: str) -> None:
        with SessionLocal() as db:
            deleted = (
                db.query(RuntimeLock)
                .filter(RuntimeLock.lock_key == key, RuntimeLock.owner_id == self.owner_id)
                .delete(synchronize_session=False)
            )
            if deleted:
                db.commit()
                return
            db.rollback()

    def is_locked(self, key: str) -> bool:
        now = utcnow_naive()
        with SessionLocal() as db:
            row = db.query(RuntimeLock).filter(RuntimeLock.lock_key == key).first()
            if not row:
                return False
            if row.expires_at <= now:
                db.delete(row)
                db.commit()
                return False
            return True


runtime_lock_service = RuntimeLockService()
