"""Tests for Ollama provider helpers."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.provider import (
    OLLAMA_KEEP_ALIVE,
    OLLAMA_NUM_CTX_TRANSLATION_DEFAULT,
    append_ollama_no_think,
    ollama_generate_text,
    ollama_request_options,
    resolve_ollama_no_think,
    resolve_ollama_num_ctx,
)


def test_append_ollama_no_think_when_enabled():
    assert append_ollama_no_think("你是一个翻译助手。", enabled=True) == "你是一个翻译助手。 /no_think"


def test_append_ollama_no_think_skips_when_disabled():
    assert append_ollama_no_think("你是一个翻译助手。", enabled=False) == "你是一个翻译助手。"


def test_append_ollama_no_think_idempotent():
    text = "你是一个翻译助手。 /no_think"
    assert append_ollama_no_think(text, enabled=True) == text


def test_ollama_request_options():
    opts = ollama_request_options(temperature=0.1)
    assert opts == {"temperature": 0.1, "num_ctx": OLLAMA_NUM_CTX_TRANSLATION_DEFAULT}


def test_resolve_ollama_num_ctx_uses_writing_default():
    assert resolve_ollama_num_ctx({}, default=8192) == 8192
    assert resolve_ollama_num_ctx({"ollama_num_ctx": 4096}, default=8192) == 4096


def test_resolve_ollama_num_ctx_snaps_to_preset():
    assert resolve_ollama_num_ctx({"ollama_num_ctx": 3000}, default=8192) == 2048
    assert resolve_ollama_num_ctx({"ollama_num_ctx": 262144}, default=2048) == 262144


def test_snap_ollama_num_ctx():
    from app.ai.provider import snap_ollama_num_ctx

    assert snap_ollama_num_ctx(8192) == 8192
    assert snap_ollama_num_ctx(5000) == 4096


def test_resolve_ollama_no_think_respects_explicit_false():
    assert resolve_ollama_no_think({}, default=True) is True
    assert resolve_ollama_no_think({"ollama_no_think": False}, default=True) is False


@pytest.mark.asyncio
async def test_ollama_generate_text_uses_streaming_generate():
    stream_lines = [
        json.dumps({"response": "Hello", "done": False}),
        json.dumps({"response": " world", "done": True}),
    ]

    async def fake_aiter_lines():
        for line in stream_lines:
            yield line

    mock_resp = MagicMock(status_code=200)
    mock_resp.aiter_lines = fake_aiter_lines

    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = AsyncMock()
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.ai.provider.httpx.AsyncClient", return_value=mock_client):
        result = await ollama_generate_text(
            api_base="http://localhost:11434",
            model="llama3",
            prompt="translate this",
            system_prompt="You are helpful.",
            temperature=0.2,
        )

    assert result == "Hello world"
    payload = mock_client.stream.call_args.kwargs["json"]
    assert payload["stream"] is True
    assert payload["keep_alive"] == OLLAMA_KEEP_ALIVE
    assert payload["options"]["num_ctx"] == OLLAMA_NUM_CTX_TRANSLATION_DEFAULT


@pytest.mark.asyncio
async def test_ollama_stream_collects_thinking_when_visible_empty():
    from app.ai.provider import _read_ollama_stream

    stream_lines = [
        json.dumps({"message": {"content": "", "thinking": "你好"}, "done": False}),
        json.dumps({"message": {"content": "", "thinking": "世界"}, "done": True}),
    ]

    def make_resp():
        async def fake_aiter_lines():
            for line in stream_lines:
                yield line

        mock_resp = MagicMock()
        mock_resp.aiter_lines = fake_aiter_lines
        return mock_resp

    with_thinking = await _read_ollama_stream(make_resp(), use_thinking_fallback=True)
    without_thinking = await _read_ollama_stream(make_resp(), use_thinking_fallback=False)

    assert with_thinking == "你好世界"
    assert without_thinking == ""


@pytest.mark.asyncio
async def test_ollama_generate_text_appends_no_think_when_requested():
    stream_lines = [json.dumps({"message": {"content": "译文"}, "done": True})]

    async def fake_aiter_lines():
        for line in stream_lines:
            yield line

    mock_resp = MagicMock(status_code=200)
    mock_resp.aiter_lines = fake_aiter_lines

    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = AsyncMock()
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.ai.provider.httpx.AsyncClient", return_value=mock_client):
        await ollama_generate_text(
            api_base="http://localhost:11434",
            model="qwen3.5:0.8b",
            prompt="translate this",
            system_prompt="你是一个严谨的翻译助手。",
            no_think=True,
        )

    payload = mock_client.stream.call_args.kwargs["json"]
    assert payload["think"] is False
    assert payload["options"]["num_ctx"] == OLLAMA_NUM_CTX_TRANSLATION_DEFAULT
