from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.processors.keyword_matcher import KeywordMatcher


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
        case_sensitive=False,
        enabled=True,
    )

    matches = matcher.match("foo bar baz", [keyword])
    assert bool(matches) is expected
