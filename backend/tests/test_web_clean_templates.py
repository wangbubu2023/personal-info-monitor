import pytest

from app.domains.fetch.web_clean.structured import extract_structured_document
from app.domains.fetch.web_clean.templates import (
    TemplateValidationError,
    render_template,
    template_matches,
    template_from_metadata,
    validate_template,
)


HTML = """
<html><head>
<meta property="og:title" content="OG title">
<script type="application/ld+json">
{"@type":"NewsArticle","headline":"Schema title","author":[{"name":"Ada"},{"name":"Lin"}]}
</script>
</head><body><article class="main"><p>Article body</p><div class="ad">Ad</div></article></body></html>
"""


def test_template_matches_and_resolves_selector_schema_and_filters():
    spec = validate_template(
        {
            "id": "example-news-v1",
            "triggers": ["https://example.com/news", "schema:@NewsArticle"],
            "article_html": "selectorHtml:article.main",
            "title": "schema:@NewsArticle:headline|trim",
            "author": "schema:@NewsArticle:author.name|join:(', ')",
            "remove_html": [".ad"],
        }
    )
    structured = extract_structured_document(HTML, page_url="https://example.com/news/1")
    assert template_matches(spec, url="https://example.com/news/1", structured=structured)
    rendered = render_template(
        spec,
        html=HTML,
        url="https://example.com/news/1",
        structured=structured,
    )
    assert rendered["title"] == "Schema title"
    assert rendered["author"] == "Ada, Lin"
    assert "Article body" in rendered["article_html"]


def test_template_validation_rejects_code_unknown_filters_and_bad_selectors():
    with pytest.raises(TemplateValidationError):
        validate_template({"id": "bad template", "title": "python:exec('x')"})
    with pytest.raises(TemplateValidationError):
        validate_template({"id": "bad-v1", "article_html": "selectorHtml:div["})
    with pytest.raises(TemplateValidationError):
        validate_template({"id": "bad-v1", "title": "preset:title|eval"})


def test_template_validation_rejects_unknown_fields_and_non_array_lists():
    with pytest.raises(TemplateValidationError, match="unknown template fields"):
        validate_template({"id": "bad-v1", "article_html": "selectorHtml:article", "exec": "oops"})
    with pytest.raises(TemplateValidationError, match="triggers must be an array"):
        validate_template({"id": "bad-v1", "triggers": "https://example.com"})
    with pytest.raises(TemplateValidationError, match="unknown preset"):
        validate_template({"id": "bad-preset-v1", "title": "preset:not-a-preset"})


def test_template_regex_trigger_times_out_fail_closed():
    spec = validate_template(
        {
            "id": "bounded-regex-v1",
            "triggers": ["regex:^(a+)+$"],
            "article_html": "selectorHtml:article",
        }
    )
    assert template_matches(spec, url=("a" * 10_000) + "!", structured={}) is False


def test_template_validation_bounds_configured_lists_and_notes():
    with pytest.raises(TemplateValidationError, match="triggers has more than 32"):
        validate_template({
            "id": "too-many-triggers",
            "triggers": [f"https://example.com/{index}" for index in range(33)],
            "article_html": "selectorHtml:article",
        })
    with pytest.raises(TemplateValidationError, match="notes is longer"):
        validate_template({"id": "notes-too-long", "notes": "x" * 2001})
    with pytest.raises(TemplateValidationError, match="trigger is longer"):
        validate_template({
            "id": "trigger-too-long",
            "triggers": ["https://example.com/" + ("x" * 2100)],
            "article_html": "selectorHtml:article",
        })


def test_non_object_template_metadata_fails_closed():
    with pytest.raises(TemplateValidationError, match="must be an object"):
        template_from_metadata({"web_clean_template": "selectorHtml:article"})


def test_template_selector_output_is_bounded_fail_closed():
    spec = validate_template(
        {"id": "too-broad-v1", "article_html": "selectorHtml:p"}
    )
    html = "<article>" + "".join(f"<p>{index}</p>" for index in range(129)) + "</article>"

    with pytest.raises(TemplateValidationError, match="more than 128 values"):
        render_template(spec, html=html, url="https://example.com/story", structured={})
