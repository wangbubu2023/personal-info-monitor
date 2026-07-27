from app.domains.fetch.web_clean.markdown import html_to_markdown


def test_markdown_preserves_structure_and_absolute_links():
    result = html_to_markdown(
        """
        <article>
          <h2>Heading</h2>
          <blockquote>Quoted</blockquote>
          <a href="/docs">Docs</a>
          <pre><code class="language-python">print("ok")</code></pre>
          <table><thead><tr><th>Name</th></tr></thead><tbody><tr><td>PIM</td></tr></tbody></table>
        </article>
        """,
        base_url="https://example.com/a/",
    )
    assert "## Heading" in result
    assert "> Quoted" in result
    assert "[Docs](https://example.com/docs)" in result
    assert 'print("ok")' in result
    assert "| Name |" in result
    assert "| PIM |" in result
