"""Extra coverage for :mod:`app.domains.ingest.keywords.matcher`."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domains.ingest.keywords.matcher import KeywordMatcher


def _make_keyword(**overrides) -> SimpleNamespace:
    defaults = dict(
        id="k",
        keyword="Python",
        color="#ff4d4f",
        match_type="contains",
        match_scope="title_content",
        case_sensitive=False,
        equivalent_terms=[],
        enabled=True,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestMatcherMatch:
    def test_empty_keywords(self):
        assert KeywordMatcher().match("", "", []) == []

    def test_disabled_keyword_skipped(self):
        matcher = KeywordMatcher()
        keyword = _make_keyword(enabled=False)
        assert matcher.match("Python is great", "", [keyword]) == []

    def test_contains_match_title_scope(self):
        matcher = KeywordMatcher()
        keyword = _make_keyword(match_type="contains")
        matches = matcher.match("Python is great", "body", [keyword])
        assert len(matches) == 1
        assert matches[0]["matched_scope"] == "title"
        assert matches[0]["matched_term"] == "Python"

    def test_case_sensitive_match(self):
        matcher = KeywordMatcher()
        keyword = _make_keyword(match_type="contains", case_sensitive=True, keyword="Python")
        assert matcher.match("python IS great", "", [keyword]) == []
        assert matcher.match("Python IS great", "", [keyword])

    def test_exact_word_boundary(self):
        matcher = KeywordMatcher()
        keyword = _make_keyword(match_type="exact", keyword="api")
        assert matcher.match("API design", "", [keyword])
        assert matcher.match("apify", "", [keyword]) == []

    def test_exact_non_ascii_keyword(self):
        matcher = KeywordMatcher()
        keyword = _make_keyword(match_type="exact", keyword="人工智能")
        assert matcher.match("人工智能研究", "", [keyword])

    def test_regex_match(self):
        matcher = KeywordMatcher()
        keyword = _make_keyword(match_type="regex", keyword=r"foo\d+")
        assert matcher.match("see foo123", "", [keyword])
        assert matcher.match("no match here", "", [keyword]) == []

    def test_regex_compilation_error_returns_no_match(self):
        matcher = KeywordMatcher()
        keyword = _make_keyword(match_type="regex", keyword=r"(unclosed")
        assert matcher.match("anything", "", [keyword]) == []

    def test_unknown_match_type(self):
        matcher = KeywordMatcher()
        keyword = _make_keyword(match_type="fuzzy", keyword="x")
        assert matcher.match("x", "", [keyword]) == []


class TestRegexPatternValidation:
    @pytest.mark.parametrize(
        "pattern,ok",
        [
            ("", False),
            ("a" * 300, False),
            (r"\1backref", False),
            (r"(?<=x)y", False),
            (r"(?<!x)y", False),
            (r"(a+)++", False),
            (r"a++", False),
            (r"(valid|pattern)", True),
        ],
    )
    def test_validator(self, pattern, ok):
        matcher = KeywordMatcher()
        is_safe, _ = matcher._validate_regex_pattern(pattern)
        assert is_safe is ok


class TestHighlightAndContext:
    def test_highlight_empty_matches_returns_text(self):
        matcher = KeywordMatcher()
        assert matcher.highlight_matches("hello", []) == "hello"

    def test_highlight_wraps_keyword_case_insensitive(self):
        matcher = KeywordMatcher()
        matches = [{"keyword": "Python", "color": "#ff0000"}]
        out = matcher.highlight_matches("Python and python", matches)
        assert out.count("<mark") == 2
        assert "#ff0000" in out

    def test_highlight_longer_keyword_first(self):
        matcher = KeywordMatcher()
        matches = [
            {"keyword": "AI", "color": "#111"},
            {"keyword": "AIOps", "color": "#222"},
        ]
        out = matcher.highlight_matches("AIOps and AI", matches)
        # AIOps should be wrapped with #222
        assert "#222" in out
        assert "#111" in out

    def test_context_snippet_truncation(self):
        matcher = KeywordMatcher()
        text = "x" * 150 + "keyword" + "y" * 150
        contexts = matcher.get_match_context(text, "keyword", context_chars=20)
        assert len(contexts) == 1
        assert contexts[0].startswith("...")
        assert contexts[0].endswith("...")

    def test_context_no_match(self):
        matcher = KeywordMatcher()
        assert matcher.get_match_context("abc", "xyz") == []
