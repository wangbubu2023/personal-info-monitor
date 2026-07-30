from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.platform.browser.session_runtime import build_browser_session_runtime
from app.utils.datetime import utcnow_naive


def _runtime_for_host(tmp_path, host: str) -> dict:
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    session_id = uuid4()
    session = SimpleNamespace(
        id=session_id,
        site_url=f"https://www.{host}/",
        site_host=host,
        profile_name=host,
        user_data_dir=str(profile_dir),
        storage_state_path=None,
        session_mode="persistent_profile",
        status="active",
        last_validated_at=utcnow_naive() - timedelta(minutes=5),
        metadata_={
            "last_validation": {
                "cookie_count": 46,
                "paragraph_count": 0,
            }
        },
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = session
    source = SimpleNamespace(
        id=uuid4(),
        metadata_={"browser_session_id": str(session_id)},
    )

    runtime = build_browser_session_runtime(db, source)
    assert runtime is not None
    return runtime


def test_wsj_cookie_validation_is_runtime_ready_without_article_paragraphs(tmp_path):
    runtime = _runtime_for_host(tmp_path, "wsj.com")

    assert runtime["validation_cookie_count"] == 46
    assert runtime["validation_paragraph_count"] == 0
    assert runtime["auth_ready"] is True
    assert runtime["auth_warning"] is None


def test_generic_site_still_requires_article_paragraphs(tmp_path):
    runtime = _runtime_for_host(tmp_path, "example.com")

    assert runtime["auth_ready"] is False
    assert runtime["auth_warning"] == "浏览器会话校验未确认可读取正文段落，需要重新校验"
