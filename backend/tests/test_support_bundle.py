from __future__ import annotations

import json
import zipfile
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import BrowserSession, Source, SourceFetchLog
from app.models.browser_session import BrowserSessionStatus
from app.models.source import SourceType


def test_support_bundle_exports_redacted_diagnostics(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    settings = SimpleNamespace(
        data_dir=str(data_dir),
        fetch_concurrency=8,
        openai_api_key=None,
        cloud_fallback_enabled=False,
    )

    from app.domains.system import doctor as doctor_module
    from app.domains.system import support_bundle as bundle_module

    monkeypatch.setattr(bundle_module, "get_settings", lambda: settings)
    monkeypatch.setattr(doctor_module, "settings", settings)

    engine = create_engine(f"sqlite:///{tmp_path / 'pim.db'}", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        source = Source(
            name="Example",
            type=SourceType.RSS,
            url="https://example.com/feed?token=secretquery",
            enabled=True,
            last_error="api_key=abcdef123456 failed",
            error_count=2,
            last_fetched_at=datetime(2026, 7, 8, 8, 10, 0),
            session_health_status="error",
            session_health_reason="expired",
        )
        db.add(source)
        db.flush()
        db.add(
            SourceFetchLog(
                source_id=source.id,
                outcome="failure",
                severity="error",
                failure_code="http_403",
                saved_count=0,
                fulltext_ok=0,
                fulltext_total=1,
            )
        )
        db.add(
            BrowserSession(
                site_url="https://example.com/login?session=secretquery",
                site_host="example.com",
                profile_name="example",
                user_data_dir=str(tmp_path / "private-profile"),
                status=BrowserSessionStatus.ERROR,
                last_error="auth_token: ghijklmnop expired",
            )
        )
        db.commit()

        out = tmp_path / "bundle.zip"
        path = bundle_module.SupportBundleService(db).build_bundle(out)

        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            assert {
                "SUMMARY.md",
                "manifest.json",
                "doctor.json",
                "health.json",
                "metrics.json",
                "queue.json",
                "failed_sources.json",
                "recent_fetches.json",
                "browser_sessions.json",
                "issue_template.md",
            }.issubset(names)
            failed = json.loads(zf.read("failed_sources.json"))
            browser_sessions = json.loads(zf.read("browser_sessions.json"))
            raw_zip_text = "\n".join(zf.read(name).decode("utf-8") for name in names if name.endswith((".json", ".md")))

        assert failed["counts"]["total"] == 1
        assert failed["failed_sources"][0]["url"] == "https://example.com/feed"
        assert browser_sessions[0]["site_url"] == "https://example.com/login"
        assert "abcdef123456" not in raw_zip_text
        assert "ghijklmnop" not in raw_zip_text
        assert "secretquery" not in raw_zip_text
        assert "pim.db" not in names
    finally:
        db.close()
        engine.dispose()
