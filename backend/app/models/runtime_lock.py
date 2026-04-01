"""Runtime lock model for cross-process coordination."""

from sqlalchemy import Column, DateTime, String

from app.database import Base
from app.utils.datetime import utcnow_naive


class RuntimeLock(Base):
    """Distributed lock row stored in SQLite for multi-process safety."""

    __tablename__ = "runtime_locks"

    lock_key = Column(String(255), primary_key=True)
    owner_id = Column(String(128), nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive, nullable=False)
