from app.domains.fetch.web_clean import CleanInput, WebDocumentExtractor


def test_extractor_returns_clean_result_trace_and_structured_metadata():
    body = " ".join(["A substantial article paragraph with useful reporting and context."] * 35)
    html = f"""
    <html><head>
      <link rel="canonical" href="/canonical">
      <script type="application/ld+json">
      {{"@type":"NewsArticle","headline":"A useful report","author":{{"name":"Reporter"}},
        "datePublished":"2026-07-24T08:00:00Z","articleBody":{body!r}}}
      </script>
    </head><body>
      <nav>Navigation</nav>
      <article><h1>A useful report</h1><p>{body}</p></article>
      <footer>Copyright</footer>
    </body></html>
    """.replace("'", '"')
    result = WebDocumentExtractor().extract_sync(
        CleanInput(url="https://example.com/story", raw_html=html)
    )
    assert result.title == "A useful report"
    assert result.author == "Reporter"
    assert result.canonical_url == "https://example.com/canonical"
    assert result.article_text
    assert result.extraction_method
    assert result.trace["selected_method"] == result.extraction_method
    assert result.trace["candidates"]
    metadata = result.to_metadata()
    assert metadata["text_chars"] == len(result.article_text)
    assert metadata["quality_score"] == result.quality_score
    assert result.production_eligible() is True


def test_template_candidate_can_win_without_disabling_generic_fallbacks():
    paragraphs = "".join(
        f"<p>Paragraph {index}: focused reporting with enough detail to remain meaningful.</p>"
        for index in range(20)
    )
    html = f"""
    <html><body>
      <main><div class="noise">Short shell</div></main>
      <section id="story">{paragraphs}</section>
    </body></html>
    """
    result = WebDocumentExtractor().extract_sync(
        CleanInput(
            url="https://example.com/story/1",
            raw_html=html,
            source_metadata={
                "web_clean_template": {
                    "id": "example-v1",
                    "triggers": ["https://example.com/story"],
                    "article_html": "selectorHtml:#story",
                }
            },
        )
    )
    assert result.template_id == "example-v1"
    assert result.extraction_method == "template_selector"
    assert "Paragraph 19" in result.article_text


def test_structured_multiple_objects_graph_and_template_published_are_resolved():
    body = " ".join(["Detailed article evidence and context for extraction."] * 40)
    html = f"""
    <html data-pim-shadow-materialized-count="3" data-pim-shadow-timeout="true"><head>
      <script type="application/ld+json">
      [
        {{"@type":"WebSite","name":"Example"}},
        {{"@graph":[
          {{"@type":"NewsArticle","headline":"","articleBody":{body!r}}},
          {{"@type":["Article","NewsArticle"],"headline":"Graph title",
            "author":[{{"name":"Ada"}},{{"name":"Lin"}}],
            "mainEntityOfPage":{{"@id":"/canonical-from-graph"}},
            "datePublished":"2026-07-24T08:00:00Z",
            "inLanguage":"zh-CN","articleBody":{body!r}}}
        ]}}
      ]
      </script>
    </head><body><article><h1>Graph title</h1><p>{body}</p></article></body></html>
    """.replace("'", '"')
    result = WebDocumentExtractor().extract_sync(
        CleanInput(
            url="https://example.com/story/1",
            raw_html=html,
            source_metadata={
                "web_clean_template": {
                    "id": "graph-v1",
                    "triggers": ["https://example.com/story"],
                    "article_html": "selectorHtml:article",
                    "published": "schema:datePublished",
                }
            },
        )
    )

    assert result.title == "Graph title"
    assert result.author == "Ada, Lin"
    assert result.canonical_url == "https://example.com/canonical-from-graph"
    assert result.language == "zh-CN"
    assert result.published_time is not None
    assert result.published_time.isoformat().startswith("2026-07-24T08:00:00")
    assert result.trace["shadow_materialized_count"] == 3
    assert result.trace["shadow_timeout"] is True


def test_invalid_template_is_reported_and_generic_fallback_remains_available():
    body = " ".join(["Fallback article paragraph with useful detail."] * 40)
    result = WebDocumentExtractor().extract_sync(
        CleanInput(
            url="https://example.com/story",
            raw_html=f"<html><body><article><p>{body}</p></article></body></html>",
            source_metadata={
                "web_clean_template": {
                    "id": "bad-v1",
                    "article_html": "selectorHtml:article",
                    "unknown": "must fail closed",
                }
            },
        )
    )

    assert result.article_text
    assert result.template_id is None
    assert result.trace["template_validation_errors"]


def test_non_article_candidate_is_never_production_eligible():
    from app.domains.fetch.web_clean.contracts import CleanResult

    result = CleanResult(
        url="https://example.com/topics",
        title="Topics",
        author=None,
        published_time=None,
        canonical_url=None,
        site_name=None,
        language=None,
        article_html="<main>links</main>",
        article_text="topic link " * 20,
        article_markdown="topic link " * 20,
        clean_full_html=None,
        extraction_method="beautifulsoup",
        template_id=None,
        quality_status="non_article",
        quality_score=0.08,
        trace={
            "selected_method": "beautifulsoup",
            "candidates": [{"method": "beautifulsoup", "rejected_reason": None}],
        },
    )
    assert result.production_eligible() is False


def test_rejected_schema_body_is_preserved_in_candidate_trace():
    body = " ".join(["Generic fallback paragraph with substantial reporting context."] * 40)
    html = f"""
    <html><head><script type="application/ld+json">
    {{"@type":"NewsArticle","headline":"Story","articleBody":"tiny"}}
    </script></head><body><article><h1>Story</h1><p>{body}</p></article></body></html>
    """

    result = WebDocumentExtractor().extract_sync(
        CleanInput(url="https://example.com/story", raw_html=html)
    )

    rejected = [item for item in result.trace["candidates"] if item.get("rejected_reason")]
    assert any(
        item["method"] == "structured_json_ld" and item["rejected_reason"] == "too_short"
        for item in rejected
    )


def test_structured_urls_reject_non_http_schemes():
    body = " ".join(["Substantial article paragraph with reporting context."] * 40)
    html = f"""
    <html><head>
      <link rel="canonical" href="javascript:alert(1)">
      <meta property="og:image" content="data:text/html,secret">
      <script type="application/ld+json">
      {{"@type":"NewsArticle","headline":"Story","url":"javascript:alert(2)",
        "image":"data:text/html,secret","articleBody":{body!r}}}
      </script>
    </head><body><article><p>{body}</p></article></body></html>
    """.replace("'", '"')

    result = WebDocumentExtractor().extract_sync(
        CleanInput(url="https://example.com/story", raw_html=html)
    )

    assert result.canonical_url is None
    assert result.metadata.get("image") is None


def test_invalid_template_configuration_is_shadow_only_even_when_generic_candidate_is_good():
    html = "<html><body><article><h1>Good title</h1>" + "<p>Useful article paragraph.</p>" * 30 + "</article></body></html>"
    result = WebDocumentExtractor().extract_sync(
        CleanInput(
            url="https://example.test/story",
            raw_html=html,
            source_metadata={"web_clean_template": {"id": "bad", "unknown": "field"}},
        )
    )

    assert result.article_text
    assert result.trace["template_validation_errors"]
    assert result.production_eligible() is False
