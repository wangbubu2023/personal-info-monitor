import pytest
from datetime import datetime

from app.domains.fetch.web_clean.filters import (
    FilterValidationError,
    apply_filters,
    validate_filters,
)


def test_filters_cover_text_html_collections_and_safe_name():
    assert apply_filters("  Hello  ", "trim|replace:('Hello','PIM')") == "PIM"
    assert "advert" not in apply_filters(
        "<article>Body<div class='ad'>advert</div></article>",
        "remove_html:('.ad')|strip_tags|trim",
    )
    assert apply_filters(["a", "b"], "join:(', ')") == "a, b"
    assert apply_filters(["a", "b"], "list") == "- a\n- b"
    assert "| name |" in apply_filters([{"name": "PIM"}], "table")
    assert apply_filters("../bad:name?.md", "safe_name") == "bad-name-.md"
    assert apply_filters(datetime(2026, 7, 24, 8, 9, 10), "date:('YYYY-MM-DDTHH:mm:ss')") == "2026-07-24T08:09:10"


def test_filters_fail_closed_for_unknown_or_unsafe_inputs():
    with pytest.raises(FilterValidationError, match="unknown filter"):
        validate_filters("eval")
    with pytest.raises(FilterValidationError, match="flags"):
        validate_filters("replace:('a','b','x')")
    with pytest.raises(FilterValidationError, match="too complex"):
        apply_filters("<p>x</p>", f"remove_html:('{' '.join(['div'] * 14)}')")


def test_filters_enforce_arity_and_attribute_allowlists():
    with pytest.raises(FilterValidationError, match="trim expects 0"):
        validate_filters("trim:('unexpected')")
    with pytest.raises(FilterValidationError, match="remove_attr expects 1..32"):
        validate_filters("remove_attr")
    with pytest.raises(FilterValidationError, match="strip_attr expects a list/tuple"):
        validate_filters("strip_attr:('href')")

    cleaned = apply_filters(
        '<a href="https://example.com" title="kept?" onclick="bad()">link</a>',
        "strip_attr:(['href'])",
    )
    assert 'href="https://example.com"' in cleaned
    assert "title=" not in cleaned
    assert "onclick=" not in cleaned
