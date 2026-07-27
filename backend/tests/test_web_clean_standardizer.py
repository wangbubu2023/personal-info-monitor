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
