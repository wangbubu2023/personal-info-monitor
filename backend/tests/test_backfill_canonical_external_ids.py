from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Content, Source
from app.models.source import SourceType
from scripts.backfill_canonical_external_ids import backfill_canonical_external_ids


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _source(db):
    source = Source(name="Example", type=SourceType.WEBSITE, url="https://example.com")
    db.add(source)
    db.flush()
    return source


def _content(source, *, external_id, original_url, title="Story"):
    return Content(
        source_id=source.id,
        external_id=external_id,
        title=title,
        original_url=original_url,
        content_type="website",
        full_content="body",
        metadata_={},
    )


def test_backfill_canonical_external_ids_dry_run_rolls_back():
    db = _session()
    try:
        source = _source(db)
        content = _content(
            source,
            external_id="http://www.example.com/news/12345/story?utm_source=x",
            original_url="https://www.example.com/news/12345/story?utm_campaign=y",
        )
        db.add(content)
        db.commit()

        stats = backfill_canonical_external_ids(db=db, dry_run=True, days=None)
        db.refresh(content)

        assert stats["metadata_updated"] == 1
        assert stats["external_id_updated"] == 1
        assert content.external_id == "http://www.example.com/news/12345/story?utm_source=x"
        assert content.metadata_ == {}
    finally:
        bind = db.get_bind()
        db.close()
        bind.dispose()


def test_backfill_canonical_external_ids_commits_safe_update():
    db = _session()
    try:
        source = _source(db)
        content = _content(
            source,
            external_id="http://www.example.com/news/12345/story?utm_source=x",
            original_url="https://www.example.com/news/12345/story?utm_campaign=y",
        )
        db.add(content)
        db.commit()

        stats = backfill_canonical_external_ids(db=db, dry_run=False, days=None)
        db.refresh(content)

        assert stats["metadata_updated"] == 1
        assert stats["external_id_updated"] == 1
        assert content.external_id == "https://example.com/article:12345"
        assert content.metadata_["canonical_external_id"] == "https://example.com/article:12345"
        assert content.metadata_["previous_external_id"] == "http://www.example.com/news/12345/story?utm_source=x"
    finally:
        bind = db.get_bind()
        db.close()
        bind.dispose()


def test_backfill_canonical_external_ids_reports_conflict_without_overwrite():
    db = _session()
    try:
        source = _source(db)
        existing = _content(
            source,
            external_id="https://example.com/article:12345",
            original_url="https://example.com/news/12345/story",
            title="Existing",
        )
        duplicate = _content(
            source,
            external_id="http://www.example.com/news/12345/story?utm_source=x",
            original_url="https://www.example.com/news/12345/story?utm_campaign=y",
            title="Duplicate",
        )
        db.add_all([existing, duplicate])
        db.commit()

        stats = backfill_canonical_external_ids(db=db, dry_run=False, days=None)
        db.refresh(duplicate)

        assert stats["external_id_conflict"] == 1
        assert duplicate.external_id == "http://www.example.com/news/12345/story?utm_source=x"
        assert duplicate.metadata_["canonical_external_id"] == "https://example.com/article:12345"
        assert duplicate.metadata_["canonical_external_id_conflict"] == "https://example.com/article:12345"
    finally:
        bind = db.get_bind()
        db.close()
        bind.dispose()
