from app.utils.text import normalize_article_text, strip_markdown


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


def test_normalize_article_text_single_newline_blocks_become_paragraphs():
    raw = "Paragraph one.\nParagraph two.\nVIDEO\nParagraph three."
    cleaned = normalize_article_text(raw)
    parts = [p for p in cleaned.split("\n\n") if p]
    assert parts == [
        "Paragraph one.",
        "Paragraph two.",
        "Paragraph three.",
    ]
