from app.domains.fetch.web_clean.html_standardizer import standardize_html


def test_standardizer_removes_noise_and_absolutizes_urls():
    result = standardize_html(
        """
        <html><body onload="bad()">
          <nav>Navigation</nav><script>alert(1)</script>
          <article style="color:red">
            <a href="/story">Story</a>
            <img src="images/photo.jpg" srcset="/small.jpg 1x, /large.jpg 2x" onerror="bad()">
            <table><tr><td>kept</td></tr></table><pre><code>print(1)</code></pre>
          </article>
        </body></html>
        """,
        base_url="https://example.com/news/",
    )
    assert "<script" not in result.html
    assert "<nav" not in result.html
    assert "onload" not in result.html
    assert "onerror" not in result.html
    assert "style=" not in result.html
    assert 'href="https://example.com/story"' in result.html
    assert 'src="https://example.com/news/images/photo.jpg"' in result.html
    assert "https://example.com/small.jpg 1x" in result.html
    assert "<table>" in result.html
    assert "<code>" in result.html


def test_standardizer_handles_empty_and_broken_html():
    assert standardize_html("").html == ""
    result = standardize_html("<article><p>broken")
    assert "broken" in result.html


def test_standardizer_handles_nested_noise_without_touching_decomposed_children():
    result = standardize_html(
        """
        <main>
          <div class="related"><a href="/related">Related story</a></div>
          <article><p>Primary article body</p></article>
        </main>
        """,
        base_url="https://example.com/news/",
    )

    assert "Related story" not in result.html
    assert "Primary article body" in result.html


def test_standardizer_uses_safe_base_promotes_lazy_media_and_drops_hidden_nodes():
    result = standardize_html(
        """
        <html data-pim-shadow-materialized-count="2" data-pim-shadow-timeout="true">
          <head><base href="https://cdn.example/assets/"></head>
          <body>
            <p hidden>secret hidden copy</p>
            <p aria-hidden="true">screen-reader hidden copy</p>
            <img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP" data-src="photo.jpg">
            <noscript>&lt;img src="fallback.jpg" alt="fallback"&gt;</noscript>
            <a href="javascript:alert(1)">bad</a>
            <a href="story.html">good</a>
          </body>
        </html>
        """,
        base_url="https://example.com/news/page",
    )

    assert "secret hidden copy" not in result.html
    assert "screen-reader hidden copy" not in result.html
    assert 'src="https://cdn.example/assets/photo.jpg"' in result.html
    assert 'src="https://cdn.example/assets/fallback.jpg"' in result.html
    assert 'href="https://cdn.example/assets/story.html"' in result.html
    assert "javascript:" not in result.html
    assert "data-pim-shadow-materialized-count" not in result.html
    assert result.trace["promoted_lazy_media"] == 1
    assert result.trace["materialized_noscript"] == 1
    assert result.trace["shadow_materialized_count"] == 2
    assert result.trace["shadow_timeout"] is True
    assert len(result.trace["input_sha256"]) == 64
    assert len(result.trace["output_sha256"]) == 64


def test_standardizer_size_cap_and_selector_guard_fail_safe():
    result = standardize_html(
        "<article>" + ("x" * 500) + "</article>",
        remove_selectors=[" ".join(["div"] * 80)],
        max_html_bytes=64,
    )

    assert result.trace["truncated"] is True
    assert result.trace["invalid_selectors"]


def test_standardizer_removes_inline_css_hidden_content():
    result = standardize_html(
        "<article><p>visible</p><div style='display: none !important'>secret</div>"
        "<span style='visibility:hidden'>hidden</span></article>",
        base_url="https://example.com/story",
    )
    assert "visible" in result.html
    assert "secret" not in result.html
    assert "hidden" not in result.html


def test_standardizer_treats_untrusted_shadow_markers_as_bounded_diagnostics():
    result = standardize_html(
        '<html data-pim-shadow-materialized-count="not-an-int">'
        '<head><base href="https://cdn.example/private/path/"></head>'
        '<body><div data-pim-shadow-root="open">visible</div></body></html>',
        base_url="https://example.com/story",
    )

    assert "visible" in result.html
    assert "data-pim-shadow" not in result.html
    assert result.trace["shadow_materialized_count"] == 1
    assert result.trace["document_base_applied"] is True
    assert "effective_base_url" not in result.trace


def test_standardizer_rejects_active_content_urls_and_embedded_objects():
    result = standardize_html(
        """
        <article>
          <a href="#section">local section</a>
          <img src="data:text/html,secret">
          <video poster="javascript:alert(1)"></video>
          <object data="https://evil.example/payload"></object>
          <embed src="https://evil.example/plugin">
          <applet>legacy plugin</applet>
        </article>
        """,
        base_url="https://example.com/story",
    )

    assert 'href="#section"' in result.html
    assert "data:text/html" not in result.html
    assert "javascript:" not in result.html
    assert "<object" not in result.html
    assert "<embed" not in result.html
    assert "<applet" not in result.html
