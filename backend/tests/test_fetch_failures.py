"""Tests for the unified fetch failure taxonomy (app.domains.fetch.failures)."""

from __future__ import annotations

import asyncio
import socket
import ssl

import aiohttp
import pytest

from app.domains.fetch.failures import (
    FetchFailure,
    FetchFailureCode,
    FetchFailureError,
    classify_exception,
    classify_http_status,
    make_failure,
    to_warning_entry,
)


# --- classify_http_status ---------------------------------------------------


def test_classify_http_status_returns_none_for_success():
    assert classify_http_status(200) is None
    assert classify_http_status(204) is None
    assert classify_http_status(301) is None  # redirects are not failures here


def test_classify_http_status_401_is_login_required():
    failure = classify_http_status(401)
    assert failure.code is FetchFailureCode.LOGIN_REQUIRED
    assert failure.retryable is False
    assert failure.severity == "error"
    assert failure.http_status == 401


def test_classify_http_status_403_not_retryable_with_cooldown():
    failure = classify_http_status(403)
    assert failure.code is FetchFailureCode.HTTP_403
    assert failure.retryable is False
    assert failure.cooldown_seconds == 3600
    assert failure.http_status == 403


def test_classify_http_status_429_retryable_and_respects_retry_after():
    default = classify_http_status(429)
    assert default.code is FetchFailureCode.HTTP_429
    assert default.retryable is True
    assert default.cooldown_seconds == 900

    with_header = classify_http_status(429, retry_after=120)
    assert with_header.cooldown_seconds == 120


def test_classify_http_status_5xx_retryable_warning():
    for status in (500, 502, 503, 599):
        failure = classify_http_status(status)
        assert failure.code is FetchFailureCode.HTTP_5XX
        assert failure.retryable is True
        assert failure.severity == "warning"
        assert failure.http_status == status


def test_classify_http_status_other_4xx_is_client_error():
    failure = classify_http_status(404)
    assert failure.code is FetchFailureCode.HTTP_CLIENT_ERROR
    assert failure.retryable is False
    assert failure.http_status == 404


# --- classify_exception: timeouts / network --------------------------------


def test_classify_timeout():
    for exc in (asyncio.TimeoutError(), TimeoutError("read timed out")):
        failure = classify_exception(exc)
        assert failure.code is FetchFailureCode.TIMEOUT
        assert failure.retryable is True
        assert failure.severity == "warning"


def test_classify_generic_connection_error():
    failure = classify_exception(ConnectionResetError("peer reset"))
    assert failure.code is FetchFailureCode.CONNECTION_ERROR
    assert failure.retryable is True


def test_classify_generic_aiohttp_client_error():
    failure = classify_exception(aiohttp.ClientPayloadError("broken payload"))
    assert failure.code is FetchFailureCode.CONNECTION_ERROR


def test_classify_dns_error_from_gaierror():
    failure = classify_exception(socket.gaierror("Name or service not known"))
    assert failure.code is FetchFailureCode.DNS_ERROR
    assert failure.retryable is True


def test_classify_tls_error_from_sslerror():
    failure = classify_exception(ssl.SSLError("certificate verify failed"))
    assert failure.code is FetchFailureCode.TLS_ERROR
    assert failure.retryable is False


# --- classify_exception: HTTP response error -------------------------------


def test_classify_client_response_error_maps_status():
    request_info = aiohttp.RequestInfo(
        url="https://example.com",  # type: ignore[arg-type]
        method="GET",
        headers=aiohttp.typedefs.CIMultiDict(),  # type: ignore[attr-defined]
        real_url="https://example.com",  # type: ignore[arg-type]
    )
    exc = aiohttp.ClientResponseError(request_info, (), status=429)
    failure = classify_exception(exc)
    assert failure.code is FetchFailureCode.HTTP_429
    assert failure.http_status == 429


# --- classify_exception: ValueError from SSRF guard ------------------------


@pytest.mark.parametrize(
    "message",
    [
        "private address is not allowed: 10.0.0.1",
        "resolved to private address: 127.0.0.1",
        "localhost is not allowed",
        "unsupported scheme: ftp",
        "missing hostname",
        "Cookie host mismatch: request to evil.com but cookies belong to good.com",
    ],
)
def test_classify_ssrf_value_errors(message):
    failure = classify_exception(ValueError(message))
    assert failure.code is FetchFailureCode.SSRF_BLOCKED
    assert failure.retryable is False
    assert failure.severity == "error"


def test_classify_redirect_limit_value_error():
    failure = classify_exception(ValueError("redirect limit exceeded for https://example.com"))
    assert failure.code is FetchFailureCode.REDIRECT_BLOCKED
    assert failure.retryable is False


def test_classify_hostname_did_not_resolve_is_dns():
    failure = classify_exception(ValueError("hostname did not resolve"))
    assert failure.code is FetchFailureCode.DNS_ERROR


def test_classify_unknown_value_error_falls_through():
    failure = classify_exception(ValueError("something weird happened"))
    assert failure.code is FetchFailureCode.UNKNOWN
    assert failure.retryable is True


def test_classify_unknown_exception():
    failure = classify_exception(RuntimeError("boom"))
    assert failure.code is FetchFailureCode.UNKNOWN
    assert "boom" in failure.message


def test_classify_preclassified_failure_error():
    original = make_failure(FetchFailureCode.HTTP_403, http_status=403)
    failure = classify_exception(FetchFailureError(original))
    assert failure is original


# --- make_failure & DTO behaviour ------------------------------------------


def test_make_failure_appends_detail_to_default_message():
    failure = make_failure(FetchFailureCode.HTTP_403, detail="Cloudflare blocked")
    assert "访问被拒绝" in failure.message
    assert "Cloudflare blocked" in failure.message


def test_make_failure_message_override_wins():
    failure = make_failure(FetchFailureCode.UNKNOWN, message="custom label")
    assert failure.message == "custom label"


def test_make_failure_allows_policy_overrides():
    failure = make_failure(
        FetchFailureCode.RSS_STALE,
        retryable=True,
        severity="warning",
        cooldown_seconds=60,
    )
    assert failure.retryable is True
    assert failure.severity == "warning"
    assert failure.cooldown_seconds == 60


def test_rss_stale_is_info_severity_not_hard_error():
    failure = make_failure(FetchFailureCode.RSS_STALE)
    assert failure.severity == "info"
    assert failure.retryable is False


def test_body_incomplete_is_warning():
    failure = make_failure(FetchFailureCode.BODY_INCOMPLETE)
    assert failure.code is FetchFailureCode.BODY_INCOMPLETE
    assert failure.severity == "warning"


def test_to_dict_round_trip_fields():
    failure = make_failure(FetchFailureCode.HTTP_429, http_status=429, detail="slow down")
    data = failure.to_dict()
    assert data["code"] == "http_429"
    assert data["retryable"] is True
    assert data["http_status"] == 429
    assert data["cooldown_seconds"] == 900
    assert "details" not in data  # empty details omitted


def test_failure_is_frozen():
    failure = make_failure(FetchFailureCode.UNKNOWN)
    with pytest.raises(Exception):
        failure.code = FetchFailureCode.TIMEOUT  # type: ignore[misc]


# --- to_warning_entry bridge -----------------------------------------------


def test_to_warning_entry_shape():
    failure = make_failure(FetchFailureCode.HTTP_429, http_status=429)
    code, severity, message = to_warning_entry(failure)
    assert code == "http_429"
    assert severity == "warning"
    assert isinstance(message, str) and message


def test_to_warning_entry_truncates_message():
    failure = FetchFailure(
        code=FetchFailureCode.UNKNOWN,
        retryable=True,
        severity="error",
        message="x" * 1000,
    )
    _, _, message = to_warning_entry(failure)
    assert len(message) <= 500
