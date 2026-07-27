import pytest

from app.domains.fetch.web_clean.structured import extract_structured_document
from app.domains.fetch.web_clean.templates import (
    TemplateValidationError,
    render_template,
    template_matches,
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
