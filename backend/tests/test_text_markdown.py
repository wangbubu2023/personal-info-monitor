from app.utils.text import html_to_text_preserving_blocks, normalize_article_text, strip_markdown


SAMPLE = (
    "**Summary** Gas prices are approaching historic highs this Memorial Day weekend "
    "as the war with Iran disrupts global energy markets."
    "The national average is expected to reach about $4.48 per gallon, "
    "with analysts warning prices could hit $5 next month."
    "Just 21% of Americans approve of President Trump's handling of gas prices, "
    "according to a CNN poll.\n\n"
    "The war with Iran has [destabilized the global energy system]"
    "(https://www.cnn.com/2026/05/12/business/gas-prices-oil-trump-iran), "
    "pushing up pump prices across the country [despite emergency steps]"
    "(https://www.cnn.com/2026/05/18/business/gas-prices-trump-iran-hormuz) "
    "from the Trump administration designed to limit the damage."
)


def test_strip_markdown_removes_bold_and_link_urls():
    cleaned = strip_markdown(SAMPLE)

    assert "**" not in cleaned
    assert "https://www.cnn.com/" not in cleaned
    assert "destabilized the global energy system" in cleaned
    assert "despite emergency steps" in cleaned
    assert cleaned.startswith("Summary")


def test_strip_markdown_drops_image_alt_text_instead_of_promoting_it_to_body():
    raw = (
        "正文第一段。\n\n"
        "![A diagram showing that the same architecture from big Google AI models "
        "can be used on a low-end machine.](https://example.com/diagram.png)\n\n"
        "正文第二段。"
    )

    cleaned = strip_markdown(raw)

    assert "A diagram showing" not in cleaned
    assert cleaned == "正文第一段。\n\n正文第二段。"


def test_normalize_article_text_preserves_readable_sentences():
    cleaned = normalize_article_text(SAMPLE)

    assert "Summary" in cleaned
    assert "Gas prices are approaching historic highs" in cleaned
    assert "destabilized the global energy system" in cleaned
    assert "https://" not in cleaned


def test_normalize_article_text_preserves_paragraph_breaks():
    raw = "First paragraph sentence one. Sentence two.\n\nSecond paragraph here."
    cleaned = normalize_article_text(raw)
    assert cleaned.count("\n\n") == 1
    assert cleaned.startswith("First paragraph")
    assert cleaned.endswith("Second paragraph here.")


def test_normalize_article_text_strips_embed_noise_lines():
    raw = (
        "Lead paragraph about OpenAI.\n\n"
        "VIDEO\n\n"
        "Next paragraph after an embed placeholder.\n\n"
        "Recommended"
    )
    cleaned = normalize_article_text(raw)
    assert "VIDEO" not in cleaned
    assert "Recommended" not in cleaned
    assert "Lead paragraph about OpenAI." in cleaned
    assert "Next paragraph after an embed placeholder." in cleaned
    assert cleaned.count("\n\n") == 1


def test_normalize_article_text_strips_site_ad_disclosure_paragraph():
    raw = (
        "IT之家正文第一段。\n\n"
        "广告声明：文内含有的对外跳转链接用于传递更多信息，IT之家所有文章均包含本声明。\n\n"
        "IT之家正文第二段。"
    )

    cleaned = normalize_article_text(raw)

    assert "广告声明" not in cleaned
    assert cleaned == "IT之家正文第一段。\n\nIT之家正文第二段。"


def test_normalize_article_text_single_newline_blocks_become_paragraphs():
    raw = "Paragraph one.\nParagraph two.\nVIDEO\nParagraph three."
    cleaned = normalize_article_text(raw)
    parts = [p for p in cleaned.split("\n\n") if p]
    assert parts == [
        "Paragraph one.",
        "Paragraph two.",
        "Paragraph three.",
    ]


def test_html_to_text_preserving_blocks_keeps_paragraphs_without_splitting_inline_tags():
    html = """
    <article>
      <p>第一段里有 <strong>重点词</strong> 和 <a href="/x">链接文字</a>。</p>
      <p>第二段应该作为新的 Markdown 段落。</p>
      <p>第三段继续保留。</p>
    </article>
    """

    cleaned = html_to_text_preserving_blocks(html)

    parts = [p for p in cleaned.split("\n\n") if p.strip()]
    assert parts == [
        "第一段里有 重点词 和 链接文字。",
        "第二段应该作为新的 Markdown 段落。",
        "第三段继续保留。",
    ]
