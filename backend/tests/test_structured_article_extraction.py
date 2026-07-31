"""Structured article extraction and website fetch diagnostics."""

import json

from app.domains.fetch.collectors.fetch_profile import (
    detect_paywall_vendors,
    diagnose_article_html,
    get_fetch_profile,
)
from app.utils.structured_article import extract_article_page_metadata, extract_structured_article


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


def test_extracts_current_prismic_next_article_without_read_next_posts_or_image_alt():
    intro = "The visible introduction explains the opening example in enough detail. " * 3
    section_one = "The first hidden section contains the individual effects and supporting evidence. " * 5
    section_two = "The second hidden section explains why the bias happens and how to avoid it. " * 5
    unrelated = "This is a different recommended article and must never enter the current body. " * 20
    payload = {
        "props": {
            "pageProps": {
                "page": {
                    "title": [{"type": "heading1", "text": "Current Prismic Article"}],
                    "excerpt_title": [{"type": "heading2", "text": "What is this bias?"}],
                    "excerpt": [
                        {"type": "paragraph", "text": "A concise definition of the current bias."},
                        {"type": "image", "alt": "Decorative image alt that is not body text"},
                    ],
                    "intro_section_title": [{"type": "heading2", "text": "Where this bias occurs"}],
                    "intro_section_body": [{"type": "paragraph", "text": intro}],
                    "body": [
                        {
                            "slice_type": "content_section",
                            "primary": {
                                "title": [{"type": "heading2", "text": "Individual effects"}],
                                "content_block": [{"type": "paragraph", "text": section_one}],
                            },
                        },
                        {
                            "slice_type": "content_section",
                            "primary": {
                                "title": [{"type": "heading2", "text": "How to avoid it"}],
                                "content_block": [{"type": "paragraph", "text": section_two}],
                            },
                        },
                        {
                            "slice_type": "content_section",
                            "primary": {
                                "title": [{"type": "heading2", "text": "Related TDL articles"}],
                                "content_block": [{"type": "paragraph", "text": unrelated}],
                            },
                        },
                    ],
                    "sources": [{"type": "o-list-item", "text": "A relevant source citation."}],
                    "read_next_posts": [{"post": {"content": unrelated}}],
                }
            }
        }
    }
    html = (
        "<html><body><p>Only the short intro is server-rendered.</p>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        "</body></html>"
    )

    result = extract_structured_article(html, min_chars=120)

    assert result is not None
    assert result.method == "prismic_next_data"
    assert result.title == "Current Prismic Article"
    assert "Individual effects" in result.text
    assert "How to avoid it" in result.text
    assert "A relevant source citation." in result.text
    assert unrelated.strip() not in result.text
    assert "Decorative image alt" not in result.text
    assert result.signals["section_count"] == 2
    assert result.signals["skipped_related_sections"] == 1


def test_extracts_short_cls_telegraph_from_item_scoped_next_data():
    html = """
    <html><body>
      <nav>关于我们 网站声明 首页 电报 关联话题</nav>
      <script id="__NEXT_DATA__" type="application/json">
      {
        "props": {
          "pageProps": {
            "articleDetail": {
              "id": 2438608,
              "title": "财联社7月28日电，上期所原油主力合约日内跌幅扩大至6%，报531.1元/桶。",
              "content": "财联社7月28日电，上期所原油主力合约日内跌幅扩大至6%，报531.1元/桶。",
              "ctime": 1785205935
            }
          }
        }
      }
      </script>
      <footer>沪ICP备14040942号-9 沪公网安备31010402006047号</footer>
    </body></html>
    """

    result = extract_structured_article(html, min_chars=120)

    assert result is not None
    assert result.method == "cls_next_data"
    assert result.text == (
        "2026年07月28日 10:32:15\n\n"
        "财联社7月28日电，上期所原油主力合约日内跌幅扩大至6%，报531.1元/桶。"
    )
    assert "关于我们" not in result.text
    assert result.signals["body_key"] == "props.pageProps.articleDetail.content"

    metadata = extract_article_page_metadata(
        html,
        page_url="https://www.cls.cn/detail/2438608",
    )
    assert metadata["published_time"].isoformat() == "2026-07-28T02:32:15+00:00"
    assert metadata["published_time_raw"] == "1785205935"


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


def test_rejects_long_flat_plaintext_json_ld_body():
    flat_body = "虎嗅结构化正文没有任何段落边界但长度很长。" * 180
    visible_article = "".join(
        f"<p>第{i}段可见正文，包含真实段落边界和足够的正文信息。</p>"
        for i in range(1, 10)
    )
    html = f"""
    <html><head>
      <script type="application/ld+json">
        {{
        "@type": "NewsArticle",
        "headline": "虎嗅长文",
        "articleBody": {json.dumps(flat_body, ensure_ascii=False)}
      }}
      </script>
    </head><body><article>{visible_article}</article></body></html>
    """

    result = extract_structured_article(html, min_chars=80)

    assert result is None


def test_extracts_wallstreetcn_public_article_body_without_related_links():
    html = """
    <html><body>
      <article>
        <header>
          <h1>东鹏饮料上半年收入增长16%</h1>
          <time datetime="2026-07-31T07:53:59.000Z">15:53</time>
        </header>
        <section class="_articleBody_15gzr_1 article">
          <p>东鹏饮料仍在增长，但驱动力正在从单一大单品转向更多品类共同拉动。</p>
          <p>上半年，公司实现营业收入124.43亿元，同比增长15.9%；归母净利润28.67亿元，同比增长20.7%。</p>
          <p>新品推广和渠道扩张仍需要较高投入，公司将继续提升单点销售产出。</p>
        </section>
      </article>
      <section>相关文章：这不是当前文章正文，不能混入提取结果。</section>
    </body></html>
    """

    result = extract_structured_article(html, min_chars=80)

    assert result is not None
    assert result.method == "wallstreetcn_article_body"
    assert result.title == "东鹏饮料上半年收入增长16%"
    assert "营业收入124.43亿元" in result.text
    assert "相关文章" not in result.text
    assert result.signals["published_time"] == "2026-07-31T07:53:59+00:00"

    metadata = extract_article_page_metadata(html, page_url="https://wallstreetcn.com/articles/3778418")
    assert metadata["published_time"].isoformat() == "2026-07-31T07:53:59+00:00"
    assert metadata["published_time_raw"] == "2026-07-31T07:53:59.000Z"


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
