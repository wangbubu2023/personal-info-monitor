"""Tests for keyword content filtering in the fetch pipeline."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.domains.fetch.coordinator import _apply_keyword_filter


def _make_keyword(kid: str, word: str, match_type: str = "contains", enabled: bool = True):
    return SimpleNamespace(
        id=kid, keyword=word, match_type=match_type,
        match_scope="title_content", equivalent_terms=[],
        case_sensitive=False, enabled=enabled, color="#ff0000",
    )


def _make_content(title: str, body: str = ""):
    return SimpleNamespace(
        title=title, full_content=body or None,
        summary=None, keyword_matches=[],
    )


class TestApplyKeywordFilter:

    def test_no_keywords_passes_all_with_warning(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        source = SimpleNamespace(name="TestSource", metadata_={})
        items = [_make_content("Hello World")]

        kept, filtered = _apply_keyword_filter(db, source, items)
        assert kept == items
        assert filtered == 0
        assert source.metadata_["warnings"] == ["keyword_filter_misconfigured"]

    def test_matching_items_kept(self):
        kw = _make_keyword("k1", "AI")
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [kw]
        source = SimpleNamespace(name="TestSource")
        items = [
            _make_content("AI breakthroughs in 2025"),
            _make_content("Weather forecast today"),
            _make_content("New AI chip released"),
        ]

        kept, filtered = _apply_keyword_filter(db, source, items)
        assert len(kept) == 2
        assert filtered == 1
        assert kept[0].title == "AI breakthroughs in 2025"
        assert kept[1].title == "New AI chip released"

    def test_keyword_matches_populated(self):
        kw = _make_keyword("k1", "blockchain")
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [kw]
        source = SimpleNamespace(name="TestSource")
        items = [_make_content("Blockchain trends")]

        kept, _ = _apply_keyword_filter(db, source, items)
        assert len(kept) == 1
        assert len(kept[0].keyword_matches) > 0
        assert kept[0].keyword_matches[0]["keyword"] == "blockchain"

    def test_body_matching(self):
        kw = _make_keyword("k1", "quantum")
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [kw]
        source = SimpleNamespace(name="TestSource")
        items = [_make_content("Tech News", body="New quantum computing paper published")]

        kept, filtered = _apply_keyword_filter(db, source, items)
        assert len(kept) == 1
        assert filtered == 0

    def test_all_filtered_out(self):
        kw = _make_keyword("k1", "crypto")
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [kw]
        source = SimpleNamespace(name="TestSource")
        items = [
            _make_content("Weather today"),
            _make_content("Sports results"),
        ]

        kept, filtered = _apply_keyword_filter(db, source, items)
        assert len(kept) == 0
        assert filtered == 2

    def test_disabled_keywords_ignored(self):
        kw_enabled = _make_keyword("k1", "AI", enabled=True)
        kw_disabled = _make_keyword("k2", "Weather", enabled=False)
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [kw_enabled, kw_disabled]
        source = SimpleNamespace(name="TestSource")
        items = [
            _make_content("AI news"),
            _make_content("Weather report"),
        ]

        kept, filtered = _apply_keyword_filter(db, source, items)
        assert len(kept) == 1
        assert kept[0].title == "AI news"

    def test_multiple_keywords_or_logic(self):
        """Content matching ANY keyword should pass."""
        kw1 = _make_keyword("k1", "AI")
        kw2 = _make_keyword("k2", "crypto")
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [kw1, kw2]
        source = SimpleNamespace(name="TestSource")
        items = [
            _make_content("AI advances"),
            _make_content("Crypto market"),
            _make_content("Sports news"),
        ]

        kept, filtered = _apply_keyword_filter(db, source, items)
        assert len(kept) == 2
        assert filtered == 1

    def test_empty_content_list(self):
        kw = _make_keyword("k1", "AI")
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [kw]
        source = SimpleNamespace(name="TestSource")

        kept, filtered = _apply_keyword_filter(db, source, [])
        assert len(kept) == 0
        assert filtered == 0

    def test_scope_and_equivalent_terms_apply(self):
        kw = _make_keyword("k1", "人工智能")
        kw.match_scope = "content"
        kw.equivalent_terms = ["AI"]
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [kw]
        source = SimpleNamespace(name="TestSource")
        items = [_make_content("市场快讯", body="AI demand keeps rising")]

        kept, filtered = _apply_keyword_filter(db, source, items)
        assert len(kept) == 1
        assert filtered == 0
        assert kept[0].keyword_matches[0]["matched_term"] == "AI"
