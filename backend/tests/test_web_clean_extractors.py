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
