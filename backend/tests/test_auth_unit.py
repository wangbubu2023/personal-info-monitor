"""Tests for app.auth — API key verification."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


class TestVerifyApiKey:

    def test_valid_key(self):
        mock_settings = MagicMock(pim_api_key="correct-key")
        with patch("app.auth.get_settings", return_value=mock_settings):
            from app.auth import verify_api_key
            result = verify_api_key(api_key="correct-key")
        assert result == "correct-key"

    def test_invalid_key_raises_401(self):
        mock_settings = MagicMock(pim_api_key="correct-key")
        with patch("app.auth.get_settings", return_value=mock_settings):
            from app.auth import verify_api_key
            with pytest.raises(HTTPException) as exc_info:
                verify_api_key(api_key="wrong-key")
            assert exc_info.value.status_code == 401

    def test_missing_key_raises_401(self):
        mock_settings = MagicMock(pim_api_key="correct-key")
        with patch("app.auth.get_settings", return_value=mock_settings):
            from app.auth import verify_api_key
            with pytest.raises(HTTPException) as exc_info:
                verify_api_key(api_key=None)
            assert exc_info.value.status_code == 401

    def test_empty_key_raises_401(self):
        mock_settings = MagicMock(pim_api_key="correct-key")
        with patch("app.auth.get_settings", return_value=mock_settings):
            from app.auth import verify_api_key
            with pytest.raises(HTTPException) as exc_info:
                verify_api_key(api_key="")
            assert exc_info.value.status_code == 401

    def test_server_no_key_configured_raises_500(self):
        mock_settings = MagicMock(pim_api_key="")
        with patch("app.auth.get_settings", return_value=mock_settings):
            from app.auth import verify_api_key
            with pytest.raises(HTTPException) as exc_info:
                verify_api_key(api_key="any-key")
            assert exc_info.value.status_code == 500
            assert "misconfigured" in exc_info.value.detail.lower()

    def test_server_none_key_configured_raises_500(self):
        mock_settings = MagicMock(pim_api_key=None)
        with patch("app.auth.get_settings", return_value=mock_settings):
            from app.auth import verify_api_key
            with pytest.raises(HTTPException) as exc_info:
                verify_api_key(api_key="any-key")
            assert exc_info.value.status_code == 500
