"""Unit tests for FTS5 query sanitization."""

from app.utils.fts_query import build_sqlite_fts5_match_expression


def test_build_fts_returns_none_for_empty():
    assert build_sqlite_fts5_match_expression("") is None
    assert build_sqlite_fts5_match_expression("   ") is None


def test_build_fts_quotes_tokens_and_joins_with_and():
    expr = build_sqlite_fts5_match_expression("hello world")
    assert expr == '"hello" AND "world"'


def test_build_fts_strips_operator_like_chars():
    expr = build_sqlite_fts5_match_expression('foo*bar OR baz')
    # * and OR-related punctuation stripped inside tokens; "OR" remains as letters
    assert "*" not in expr
    assert '"' in expr


def test_build_fts_escapes_double_quotes_in_token():
    expr = build_sqlite_fts5_match_expression('x"y')
    assert '""' in expr


def test_build_fts_none_when_only_syntax_chars():
    assert build_sqlite_fts5_match_expression("*^[]") is None
