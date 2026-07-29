from __future__ import annotations

import json
import zipfile
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import BrowserSession, Content, Source, SourceFetchLog
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
            metadata_={
                "web_clean_profile": {
                    "extraction_method": "readability",
                    "quality_status": "good",
                    "text_chars": 900,
                    "cookie": "source-profile-secret",
                }
            },
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
            Content(
                source_id=source.id,
                title="Sensitive title must not be exported",
                original_url="https://example.com/private?Authorization=content-secret",
                content_type="website",
                full_content="private article body API_KEY=body-secret-value",
                metadata_={
                    "web_clean": {
                        "version": "v1",
                        "extraction_method": "template_selector",
                        "template_id": "example",
                        "quality_status": "good",
                        "quality_score": 0.92,
                        "text_chars": 1200,
                        "trace": {
                            "selected_method": "template_selector",
                            "standardizer": {
                                "input_sha256": "a" * 64,
                                "output_sha256": "b" * 64,
                                "input_chars": 2000,
                                "output_chars": 1400,
                                "raw_html": "Authorization: trace-secret-value",
                            },
                            "candidates": [
                                {
                                    "method": "template_selector",
                                    "score": 0.92,
                                    "quality_status": "good",
                                    "text_chars": 1200,
                                    "signals": {"paragraph_count": 8, "raw_text": "body-secret-value"},
                                }
                            ],
                            "template_validation_errors": ["api_key=template-secret-value"],
                        },
                    }
                },
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
                "web_clean_diagnostics.json",
                "issue_template.md",
            }.issubset(names)
            failed = json.loads(zf.read("failed_sources.json"))
            browser_sessions = json.loads(zf.read("browser_sessions.json"))
            web_clean = json.loads(zf.read("web_clean_diagnostics.json"))
            raw_zip_text = "\n".join(zf.read(name).decode("utf-8") for name in names if name.endswith((".json", ".md")))

        assert failed["counts"]["total"] == 1
        assert failed["failed_sources"][0]["url"] == "https://example.com/feed"
        assert browser_sessions[0]["site_url"] == "https://example.com/login"
        assert failed["failed_sources"][0]["web_clean_profile"] == {
            "extraction_method": "readability",
            "quality_status": "good",
            "text_chars": 900,
        }
        assert len(web_clean) == 1
        assert web_clean[0]["content_ref"] != str(source.id)
        assert web_clean[0]["standardizer"]["input_sha256"] == "a" * 64
        assert web_clean[0]["candidates"][0]["signals"] == {"paragraph_count": 8}
        assert "abcdef123456" not in raw_zip_text
        assert "ghijklmnop" not in raw_zip_text
        assert "secretquery" not in raw_zip_text
        assert "body-secret-value" not in raw_zip_text
        assert "trace-secret-value" not in raw_zip_text
        assert "template-secret-value" not in raw_zip_text
        assert "source-profile-secret" not in raw_zip_text
        assert "Sensitive title" not in raw_zip_text
        assert "pim.db" not in names
    finally:
        db.close()
        engine.dispose()


def test_support_bundle_web_clean_numbers_reject_nan_and_infinity():
    from app.domains.system.support_bundle import _safe_web_clean_profile

    profile = _safe_web_clean_profile(
        {
            "web_clean_profile": {
                "quality_score": float("nan"),
                "link_density": float("inf"),
                "text_chars": 123,
            }
        }
    )

    assert profile == {"text_chars": 123}
