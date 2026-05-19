"""Tests for embedded-binary detection in text fields."""

from __future__ import annotations

from app.utils.text import text_looks_like_embedded_binary


def test_detects_png_magic_as_latin1_string():
    raw = (b"\x89PNG\r\n\x1a\n" + b"x" * 40).decode("latin-1")
    assert text_looks_like_embedded_binary(raw) is True


def test_detects_jpeg_magic():
    raw = (b"\xff\xd8\xff\xe0" + b"y" * 30).decode("latin-1")
    assert text_looks_like_embedded_binary(raw) is True


def test_detects_png_ihdr_heuristic():
    assert text_looks_like_embedded_binary("PNG\x00fooIHDR\x00bar") is True


def test_plain_text_not_binary():
    assert text_looks_like_embedded_binary("这是一段正常的中文摘要，用于测试不会被误判。") is False
    assert text_looks_like_embedded_binary("") is False
