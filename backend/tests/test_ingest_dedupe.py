from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domains.ingest.dedupe import mark_title_group_duplicate_members
from app.models import Content, Source
from app.models.source import SourceType
from app.utils.datetime import utcnow_naive


@pytest.fixture
def db_session_sync():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _source(name: str, *, authority_type: str = "wire", source_stars: int = 1) -> Source:
    return Source(
        name=name,
        type=SourceType.WEBSITE,
        url=f"https://{name.lower().replace(' ', '-')}.example.com",
        metadata_={"authority_type": authority_type, "source_stars": source_stars},
    )


def _content(
    source: Source,
    *,
    title: str,
    url: str,
    group_id: str = "title:canonical-quality",
    fetched_offset_minutes: int = 0,
    body: str = "",
    metadata: dict | None = None,
    read_status: bool = False,
    favorited: bool = False,
) -> Content:
    now = utcnow_naive()
    return Content(
        source=source,
        title=title,
        summary="Summary text for duplicate representative testing.",
        full_content=body,
        original_url=url,
        content_type="website",
        fetched_at=now + timedelta(minutes=fetched_offset_minutes),
        publish_time=now + timedelta(minutes=fetched_offset_minutes),
        read_status=read_status,
        favorited=favorited,
        metadata_={"duplicate_group_id": group_id, **(metadata or {})},
    )


def test_mark_title_group_duplicate_members_prefers_later_fulltext_authoritative_row(db_session_sync):
    early_summary_source = _source("Aggregator", authority_type="aggregator", source_stars=1)
    later_primary_source = _source("Primary", authority_type="primary", source_stars=3)
    early = _content(
        early_summary_source,
        title="Same story",
        url="https://aggregator.example.com/story",
        fetched_offset_minutes=-5,
        metadata={"fulltext_status": "summary_only", "content_quality": 0.3, "article_score": 40},
        read_status=True,
        favorited=True,
    )
    later = _content(
        later_primary_source,
        title="Same story",
        url="https://primary.example.com/story",
        fetched_offset_minutes=5,
        body="Paragraph one.\n\nParagraph two.\n\nParagraph three. " * 40,
        metadata={"fulltext_status": "full", "content_quality": 0.92, "article_score": 85},
    )
    db_session_sync.add_all([early_summary_source, later_primary_source, early, later])
    db_session_sync.commit()

    mark_title_group_duplicate_members(db_session_sync, early)
    db_session_sync.commit()
    db_session_sync.refresh(early)
    db_session_sync.refresh(later)

    assert later.is_duplicate is False
    assert later.duplicate_of is None
    assert later.metadata_["is_duplicate"] is False
    assert "duplicate_of" not in later.metadata_
    assert early.is_duplicate is True
    assert early.duplicate_of == str(later.id)
    assert early.metadata_["duplicate_of"] == str(later.id)
    assert later.read_status is True
    assert later.favorited is True


def test_mark_title_group_duplicate_members_uses_quality_before_freshness(db_session_sync):
    source = _source("Same Source", authority_type="wire", source_stars=2)
    partial = _content(
        source,
        title="Quality wins",
        url="https://same.example.com/partial",
        fetched_offset_minutes=10,
        metadata={"fulltext_status": "partial", "content_quality": 0.6, "article_score": 90},
    )
    full = _content(
        source,
        title="Quality wins",
        url="https://same.example.com/full",
        fetched_offset_minutes=-10,
        body="Full article paragraph.\n\n" * 80,
        metadata={"fulltext_status": "full", "content_quality": 0.85, "article_score": 70},
    )
    db_session_sync.add_all([source, partial, full])
    db_session_sync.commit()

    mark_title_group_duplicate_members(db_session_sync, partial)
    db_session_sync.commit()
    db_session_sync.refresh(partial)
    db_session_sync.refresh(full)

    assert full.is_duplicate is False
    assert partial.is_duplicate is True
    assert partial.duplicate_of == str(full.id)
