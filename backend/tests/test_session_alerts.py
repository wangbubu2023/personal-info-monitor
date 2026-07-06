from datetime import datetime, timedelta

from app.domains.fetch.session_health import SessionHealth, record_session_health
from app.domains.fetch.session_alerts import (
    session_health_warning_entry,
    stamp_session_health_alert,
)
from app.models.source import Source


def _source_with_health(reason="expired", status="error"):
    source = Source(id=1, name="Paywall", url="https://example.com", type="website")
    source.metadata_ = {
        "session_health": {
            "status": status,
            "reason": reason,
            "suggested_action": "relogin",
            "validated_at": "2026-07-03T00:00:00Z",
        }
    }
    return source


def test_session_health_warning_entry_maps_expired_to_fetch_warning():
    entry = session_health_warning_entry(_source_with_health())

    assert entry == ("session_expired", "error", "会话健康异常：expired，建议操作：relogin")


def test_session_health_warning_entry_ignores_ok_health():
    source = _source_with_health(reason="ok", status="ok")

    assert session_health_warning_entry(source) is None


def test_stamp_session_health_alert_dedupes_same_reason_for_24_hours():
    now = datetime(2026, 7, 3, 10, 0, 0)
    source = _source_with_health()

    assert stamp_session_health_alert(source, now=now) is True
    assert source.session_health_alert_reason == "expired"
    assert source.session_health_alert_sent_at == now
    assert source.metadata_["session_health_alert"]["reason"] == "expired"
    assert stamp_session_health_alert(source, now=now + timedelta(hours=1)) is False
    assert stamp_session_health_alert(source, now=now + timedelta(hours=25)) is True


def test_stamp_session_health_alert_allows_new_reason_inside_window():
    now = datetime(2026, 7, 3, 10, 0, 0)
    source = _source_with_health()

    assert stamp_session_health_alert(source, now=now) is True
    source.metadata_["session_health"]["reason"] = "captcha"

    assert stamp_session_health_alert(source, now=now + timedelta(hours=1)) is True
    assert source.metadata_["session_health_alert"]["reason"] == "captcha"


def test_session_health_warning_entry_prefers_structured_health():
    source = _source_with_health(reason="expired", status="ok")
    record_session_health(
        source,
        SessionHealth(
            status="error",
            reason="captcha",
            suggested_action="relogin",
            validated_at="2026-07-03T10:00:00Z",
        ),
    )
    source.metadata_["session_health"] = {
        "status": "ok",
        "reason": "expired",
        "suggested_action": "none",
    }

    entry = session_health_warning_entry(source)

    assert entry == ("session_captcha", "error", "会话健康异常：captcha，建议操作：relogin")
