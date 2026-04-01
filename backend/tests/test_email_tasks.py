"""Tests for app.tasks.email_tasks — email sending and digest rendering."""

from __future__ import annotations

import html as html_lib
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.email_tasks import (
    render_digest_email,
    send_email,
    send_keyword_alert,
)


# ---------------------------------------------------------------------------
# send_email
# ---------------------------------------------------------------------------

class TestSendEmail:

    @pytest.mark.asyncio
    async def test_smtp_not_configured(self):
        with patch("app.config.get_settings") as mock_settings:
            settings = MagicMock()
            settings.smtp_user = ""
            settings.smtp_password = ""
            mock_settings.return_value = settings
            result = await send_email("user@example.com", "Subject", "<p>Body</p>")
            assert result is False

    @pytest.mark.asyncio
    async def test_successful_send(self):
        with patch("app.config.get_settings") as mock_settings:
            settings = MagicMock()
            settings.smtp_user = "sender@example.com"
            settings.smtp_password = "password"
            settings.smtp_host = "smtp.example.com"
            settings.smtp_port = 587
            mock_settings.return_value = settings
            with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
                result = await send_email("user@example.com", "Subject", "<p>Body</p>")
                assert result is True
                mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_failure(self):
        with patch("app.config.get_settings") as mock_settings:
            settings = MagicMock()
            settings.smtp_user = "sender@example.com"
            settings.smtp_password = "password"
            settings.smtp_host = "smtp.example.com"
            settings.smtp_port = 587
            mock_settings.return_value = settings
            with patch("aiosmtplib.send", new_callable=AsyncMock, side_effect=Exception("SMTP error")):
                result = await send_email("user@example.com", "Subject", "<p>Body</p>")
                assert result is False

    @pytest.mark.asyncio
    async def test_custom_from_email(self):
        with patch("app.config.get_settings") as mock_settings:
            settings = MagicMock()
            settings.smtp_user = "default@example.com"
            settings.smtp_password = "password"
            settings.smtp_host = "smtp.example.com"
            settings.smtp_port = 587
            mock_settings.return_value = settings
            with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
                result = await send_email(
                    "user@example.com", "Subject", "<p>Body</p>",
                    from_email="custom@example.com",
                )
                assert result is True

    @pytest.mark.asyncio
    async def test_smtp_user_none(self):
        with patch("app.config.get_settings") as mock_settings:
            settings = MagicMock()
            settings.smtp_user = None
            settings.smtp_password = "password"
            mock_settings.return_value = settings
            result = await send_email("user@example.com", "Subject", "<p>Body</p>")
            assert result is False


# ---------------------------------------------------------------------------
# render_digest_email
# ---------------------------------------------------------------------------

class TestRenderDigestEmail:

    def _make_category(self, count, items):
        from types import SimpleNamespace
        return SimpleNamespace(count=count, items=items)

    def _make_item(self, **kwargs):
        from types import SimpleNamespace
        defaults = {"source_name": "", "title": "", "url": "", "summary": "",
                     "translated_summary": "", "keyword_matches": []}
        defaults.update(kwargs)
        kws = [SimpleNamespace(**kw) if isinstance(kw, dict) else kw
               for kw in defaults["keyword_matches"]]
        defaults["keyword_matches"] = kws
        return SimpleNamespace(**defaults)

    def _make_digest(self, total_items=2, items=None):
        if items is None:
            items = [
                self._make_item(
                    source_name="TechBlog", title="AI Advances in 2025",
                    url="https://techblog.com/ai-2025", summary="Summary of AI advances.",
                    translated_summary="AI 进展总结", keyword_matches=[{"keyword": "AI"}],
                ),
                self._make_item(
                    source_name="NewsSite", title="Market Update",
                    url="https://news.com/market", summary="Markets went up.",
                ),
            ]
        from types import SimpleNamespace
        return SimpleNamespace(
            date="2025-06-15",
            total_items=total_items,
            categories={
                "websites": self._make_category(total_items, items),
                "x_accounts": self._make_category(0, []),
                "youtube": self._make_category(0, []),
                "podcasts": self._make_category(0, []),
            },
        )

    def test_basic_rendering(self):
        digest = self._make_digest()
        result = render_digest_email(digest)
        assert "<!DOCTYPE html>" in result
        assert "每日资讯简报" in result
        assert "2025-06-15" in result
        assert "TechBlog" in result
        assert "AI Advances in 2025" in result
        assert "Market Update" in result

    def test_empty_digest(self):
        digest = self._make_digest(total_items=0, items=[])
        digest.categories["websites"] = self._make_category(0, [])
        result = render_digest_email(digest)
        assert "今日暂无更新内容" in result

    def test_keyword_rendering(self):
        digest = self._make_digest()
        result = render_digest_email(digest)
        assert "AI" in result

    def test_translated_summary_rendering(self):
        digest = self._make_digest()
        result = render_digest_email(digest)
        assert "AI 进展总结" in result

    def test_footer_present(self):
        digest = self._make_digest()
        result = render_digest_email(digest)
        assert "Personal Information Monitor" in result

    def test_stats_section(self):
        digest = self._make_digest(total_items=5)
        result = render_digest_email(digest)
        assert "5" in result


# ---------------------------------------------------------------------------
# send_keyword_alert
# ---------------------------------------------------------------------------

class TestSendKeywordAlert:

    @pytest.mark.asyncio
    async def test_no_content_found(self):
        def _build_alert():
            return None

        with patch("app.tasks.email_tasks.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            mock_thread.return_value = None
            await send_keyword_alert("content-id", "AI", "Test Title")

    @pytest.mark.asyncio
    async def test_no_email_notify(self):
        with patch("app.tasks.email_tasks.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            mock_thread.return_value = None
            await send_keyword_alert("content-id", "AI", "Test Title")

    @pytest.mark.asyncio
    async def test_sends_alerts(self):
        tasks = [("user@example.com", "关键词匹配：AI", "<html>alert</html>")]
        with patch("app.tasks.email_tasks.asyncio.to_thread", new_callable=AsyncMock, return_value=tasks):
            with patch("app.tasks.email_tasks.send_email", new_callable=AsyncMock, return_value=True) as mock_send:
                await send_keyword_alert("content-id", "AI", "Test Title")
                mock_send.assert_called_once_with("user@example.com", "关键词匹配：AI", "<html>alert</html>")

    @pytest.mark.asyncio
    async def test_empty_tasks(self):
        with patch("app.tasks.email_tasks.asyncio.to_thread", new_callable=AsyncMock, return_value=[]):
            await send_keyword_alert("content-id", "AI", "Test Title")

    @pytest.mark.asyncio
    async def test_multiple_recipients(self):
        tasks = [
            ("user1@example.com", "关键词匹配：AI", "<html>alert</html>"),
            ("user2@example.com", "关键词匹配：AI", "<html>alert</html>"),
        ]
        with patch("app.tasks.email_tasks.asyncio.to_thread", new_callable=AsyncMock, return_value=tasks):
            with patch("app.tasks.email_tasks.send_email", new_callable=AsyncMock, return_value=True) as mock_send:
                await send_keyword_alert("content-id", "AI", "Test Title")
                assert mock_send.call_count == 2


# ---------------------------------------------------------------------------
# send_daily_digest_emails (high-level flow)
# ---------------------------------------------------------------------------

class TestSendDailyDigestEmails:

    @pytest.mark.asyncio
    async def test_no_schedules(self):
        from app.tasks.email_tasks import send_daily_digest_emails

        with patch("app.tasks.email_tasks.asyncio.to_thread", new_callable=AsyncMock, return_value=[]):
            await send_daily_digest_emails()

    @pytest.mark.asyncio
    async def test_sends_emails(self):
        from app.tasks.email_tasks import send_daily_digest_emails

        tasks = [("user@example.com", "Daily Digest 2025-06-15", "<html>digest</html>")]
        with patch("app.tasks.email_tasks.asyncio.to_thread", new_callable=AsyncMock, return_value=tasks):
            with patch("app.tasks.email_tasks.send_email", new_callable=AsyncMock, return_value=True) as mock_send:
                await send_daily_digest_emails()
                mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_partial_send_failure(self):
        from app.tasks.email_tasks import send_daily_digest_emails

        tasks = [
            ("user1@example.com", "Digest", "<html>1</html>"),
            ("user2@example.com", "Digest", "<html>2</html>"),
        ]
        with patch("app.tasks.email_tasks.asyncio.to_thread", new_callable=AsyncMock, return_value=tasks):
            with patch("app.tasks.email_tasks.send_email", new_callable=AsyncMock, side_effect=[True, False]):
                await send_daily_digest_emails()
