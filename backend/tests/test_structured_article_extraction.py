"""Structured article extraction and website fetch diagnostics."""

import json

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


def test_rejects_json_ld_body_that_is_tiny_vs_visible_article_text():
    summary_body = "AI-style topic overview that is only a compressed summary of the article. " * 4
    visible_article = "Real article paragraph with reporting detail, author voice, and source evidence. " * 80
    html = f"""
    <html><head>
      <script type="application/ld+json">
      {{
        "@type": "NewsArticle",
        "headline": "Important Report",
        "articleBody": "{summary_body}"
      }}
      </script>
    </head><body><article>{visible_article}</article></body></html>
    """

    result = extract_structured_article(html, min_chars=80)

    assert result is None


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


def test_extracts_structured_html_body_with_paragraph_breaks():
    html_body = "".join(
        f"<p>第{i}段虎嗅正文，包含足够的中文内容用于验证段落边界不会被拍平。</p>"
        for i in range(1, 6)
    )
    html = f"""
    <html><head>
      <script type="application/ld+json">
        {{
        "@type": "NewsArticle",
        "headline": "虎嗅长文",
        "contentHtml": {json.dumps(html_body, ensure_ascii=False)}
      }}
      </script>
    </head><body><article>{html_body}</article></body></html>
    """

    result = extract_structured_article(html, min_chars=80)

    assert result is not None
    assert result.method == "json_ld"
    parts = [p for p in result.text.split("\n\n") if p.strip()]
    assert len(parts) == 5
    assert parts[0].startswith("第1段虎嗅正文")
    assert parts[-1].startswith("第5段虎嗅正文")


def test_extracts_36kr_newsflash_detail_without_next_item():
    html = """
    <html><body>
      <script>
      window.initialState={
        "newsflashDetail": {
          "detailData": {
            "data": {
              "widgetTitle": "快手：平台累计催生189个新职业",
              "widgetContent": "36氪获悉，6月2日，快手发布《2025年度快手企业社会责任报告》。报告显示，平台累计催生189个新职业，其中由AI发展带来的新职业达到15个。"
            }
          },
          "detailNextData": {
            "data": {
              "nextItem": {
                "itemTitle": "沪深两市成交额突破2.5万亿元",
                "itemContent": "36氪获悉，沪深两市成交额突破2.5万亿元。"
              }
            }
          },
          "hotList": [
            {"templateMaterial": {"widgetTitle": "豆包6月下旬正式付费"}}
          ]
        }
      };
      </script>
      <div class="kr-newsflash-detail">
        <p>36氪获悉，6月2日，快手发布《2025年度快手企业社会责任报告》。</p>
        <div class="next-newsflash">
          <h2>下一篇</h2>
          <h3>沪深两市成交额突破2.5万亿元</h3>
          <p>36氪获悉，沪深两市成交额突破2.5万亿元。</p>
        </div>
      </div>
    </body></html>
    """

    result = extract_structured_article(html, min_chars=60)

    assert result is not None
    assert result.method == "36kr_newsflash_state"
    assert result.title == "快手：平台累计催生189个新职业"
    assert "平台累计催生189个新职业" in result.text
    assert "沪深两市成交额突破2.5万亿元" not in result.text
    assert "豆包6月下旬正式付费" not in result.text


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
