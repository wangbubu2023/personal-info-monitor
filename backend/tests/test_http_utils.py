"""Tests for :mod:`app.utils.http`.

Covers the :func:`permissive_session_kwargs` helper we introduced to
work around aiohttp's default 8 KiB header limit, which was tripping
fetches against X/NYT/WSJ whose CSP/Report-To headers routinely exceed
that threshold.

The end-to-end smoke test stands up a local aiohttp server that emits
an oversized header and asserts the helper-backed session succeeds
while a stock session raises ``ValueError`` (proof the default is
indeed too tight).
"""

from __future__ import annotations

import socket
from contextlib import closing

import aiohttp
import pytest
from aiohttp import web

from app.utils.http import LARGE_HEADER_LIMIT, permissive_session_kwargs


def _pick_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_permissive_session_kwargs_sets_header_limits() -> None:
    kwargs = permissive_session_kwargs()
    assert kwargs["max_line_size"] == LARGE_HEADER_LIMIT
    assert kwargs["max_field_size"] == LARGE_HEADER_LIMIT
    assert LARGE_HEADER_LIMIT >= 32 * 1024, "ceiling must comfortably clear 8 KiB stock limit"


def test_permissive_session_kwargs_merges_overrides() -> None:
    timeout = aiohttp.ClientTimeout(total=5)
    kwargs = permissive_session_kwargs(timeout=timeout, headers={"X-Test": "1"})
    assert kwargs["timeout"] is timeout
    assert kwargs["headers"] == {"X-Test": "1"}
    assert kwargs["max_line_size"] == LARGE_HEADER_LIMIT


def test_permissive_session_kwargs_respects_explicit_overrides() -> None:
    kwargs = permissive_session_kwargs(max_line_size=12345, max_field_size=67890)
    assert kwargs["max_line_size"] == 12345
    assert kwargs["max_field_size"] == 67890


@pytest.mark.asyncio
async def test_oversized_header_succeeds_with_permissive_session() -> None:
    oversized_value = "x" * 20000  # 20 KiB — well above stock 8190-byte ceiling

    async def handler(_request: web.Request) -> web.Response:
        return web.Response(
            text="ok",
            headers={"X-Oversized": oversized_value},
        )

    app = web.Application()
    app.router.add_get("/", handler)

    port = _pick_free_port()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()

    url = f"http://127.0.0.1:{port}/"
    try:
        # Sanity check: stock client rejects the response because the
        # header exceeds aiohttp's default 8 KiB limit.
        with pytest.raises((aiohttp.ClientError, ValueError)):
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    await response.text()

        # With the helper applied the same response is parsed fine.
        async with aiohttp.ClientSession(**permissive_session_kwargs()) as session:
            async with session.get(url) as response:
                assert response.status == 200
                assert response.headers["X-Oversized"] == oversized_value
                assert await response.text() == "ok"
    finally:
        await runner.cleanup()
