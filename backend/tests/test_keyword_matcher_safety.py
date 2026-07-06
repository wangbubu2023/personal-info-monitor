from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domains.ingest.keywords.matcher import KeywordMatcher


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        (r"(a+)+$", False),
        (r"(?<=foo)bar", False),
        (r"(foo|bar)", True),
    ],
)
def test_keyword_matcher_rejects_unsafe_regex_patterns(pattern, expected):
    matcher = KeywordMatcher()
    keyword = SimpleNamespace(
        id="k1",
        keyword=pattern,
        color="#ff4d4f",
        match_type="regex",
        match_scope="title_content",
        case_sensitive=False,
        equivalent_terms=[],
        enabled=True,
    )

    matches = matcher.match("foo bar baz", "", [keyword])
    assert bool(matches) is expected


def test_keyword_matcher_respects_match_scope_and_equivalent_terms():
    matcher = KeywordMatcher()
    keyword = SimpleNamespace(
        id="k2",
        keyword="人工智能",
        color="#1677ff",
        match_type="contains",
        match_scope="content",
        case_sensitive=False,
        equivalent_terms=["AI"],
        enabled=True,
    )

    matches = matcher.match("AI policy update", "The latest AI model ships today.", [keyword])
    assert len(matches) == 1
    assert matches[0]["matched_scope"] == "content"
    assert matches[0]["matched_term"] == "AI"


def test_keyword_matcher_title_scope_ignores_body_hits():
    matcher = KeywordMatcher()
    keyword = SimpleNamespace(
        id="k3",
        keyword="Deepfake",
        color="#1677ff",
        match_type="contains",
        match_scope="title",
        case_sensitive=False,
        equivalent_terms=["深度伪造"],
        enabled=True,
    )

    matches = matcher.match("Tech digest", "This article discusses deepfake risks.", [keyword])
    assert matches == []
