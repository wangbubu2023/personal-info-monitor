"""Structured article extraction and website fetch diagnostics."""

from app.domains.fetch.collectors.fetch_profile import (
    detect_paywall_vendors,
    diagnose_article_html,
    get_fetch_profile,
)
from app.utils.structured_article import extract_structured_article


def test_extracts_json_ld_article_body():
    html = """
    <html><head>
      <script type="application/ld+json">
      {
        "@type": "NewsArticle",
        "headline": "Important Report",
        "articleBody": "Paragraph one explains the important report. Paragraph two adds details. Paragraph three adds context."
      }
      </script>
    </head><body><p>Subscribe to continue</p></body></html>
    """

    result = extract_structured_article(html, min_chars=80)

    assert result is not None
    assert result.method == "json_ld"
    assert result.title == "Important Report"
    assert "Paragraph two adds details" in result.text


def test_extracts_next_data_content_html():
    html = """
    <html><body>
      <script id="__NEXT_DATA__" type="application/json">
      {
        "props": {
          "pageProps": {
            "article": {
              "title": "Next Story",
              "contentHtml": "<p>First paragraph from Next data.</p><p>Second paragraph carries the actual body.</p>"
            }
          }
        }
      }
      </script>
    </body></html>
    """

    result = extract_structured_article(html, min_chars=60)

    assert result is not None
    assert result.method == "next_data"
    assert "Second paragraph carries the actual body" in result.text
    assert "<p>" not in result.text


def test_fetch_profile_and_vendor_diagnostics_are_conservative():
    profile = get_fetch_profile("https://www.reuters.com/world/example")
    assert profile["structured_first"] is True
    assert "arcxp" in profile["known_paywall_vendors"]

    html = '<script src="https://www.reuters.com/arc/subs/p.min.js"></script>'
    vendors = detect_paywall_vendors(html, "https://www.reuters.com/world/example")
    assert vendors == [{"code": "arcxp", "label": "Arc XP subscriptions"}]

    diag = diagnose_article_html("Subscribe to continue", "https://www.reuters.com/world/example", profile)
    assert diag["shell_like"] is True
    assert diag["profile_known_paywall_vendors"] == ["arcxp"]
