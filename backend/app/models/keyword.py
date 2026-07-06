"""Keyword model for content monitoring."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Enum, String, Text

from app.utils.datetime import utcnow_naive
from app.database import Base, UUIDString


class MatchType(str, enum.Enum):
    """Type of keyword matching."""
    EXACT = "exact"
    CONTAINS = "contains"
    REGEX = "regex"


class MatchScope(str, enum.Enum):
    """Where a keyword should be matched."""
    TITLE = "title"
    CONTENT = "content"
    TITLE_CONTENT = "title_content"


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    """Persist enum values instead of enum member names."""
    return [str(member.value) for member in enum_cls]


class Keyword(Base):
    """Keyword for content monitoring and alerts."""

    __tablename__ = "keywords"

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    keyword = Column(String(255), nullable=False)
    # NFKC + casefold，与 app.domains.ingest.keywords.rules.keyword_identity_key 一致；唯一约束防止 Google/google 重复入库
    keyword_identity = Column(String(512), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)

    # Matching configuration
    match_type = Column(
        Enum(MatchType, values_callable=_enum_values, native_enum=False),
        default=MatchType.CONTAINS,
    )
    match_scope = Column(
        Enum(MatchScope, values_callable=_enum_values, native_enum=False),
        default=MatchScope.TITLE_CONTENT,
    )
    case_sensitive = Column(Boolean, default=False)
    equivalent_terms = Column(JSON, default=list)
    manual_equivalent_terms = Column(JSON, default=list)
    include_auto_equivalent_terms = Column(Boolean, default=True)

    # Notification settings（默认关闭；通知通道未就绪前不打扰用户）
    notify = Column(Boolean, default=False)
    notify_email = Column(Boolean, default=False)

    # Styling
    color = Column(String(7), default="#ff4d4f")

    # Status
    enabled = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    def __repr__(self) -> str:
        return f"<Keyword(id={self.id}, keyword='{self.keyword}')>"
