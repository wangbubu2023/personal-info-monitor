from app.api.contents import (
    _derive_title_from_body,
    _extract_x_article_url,
    _is_valid_title_translation,
    _split_for_reader,
    _title_looks_like_url,
)


def test_split_for_reader_keeps_abbreviation_sentence():
    text = "The build up of U.S. troops increased risk. Markets moved lower."
    parts = _split_for_reader(text)
    assert "U.S." in parts[0]
    assert len(parts) == 2


def test_split_for_reader_preserves_paragraph_blocks():
    text = (
        "OpenAI is reportedly preparing to file for an IPO. "
        "The IPO could take place as soon as September.\n\n"
        "This is all according to a pair of company insiders who spoke to the paper. "
        "They said that OpenAI has been laying the groundwork.\n\n"
        "Finally, there's the notion of its valuation."
    )
    parts = _split_for_reader(text)
    assert len(parts) == 3
    assert parts[0].startswith("OpenAI is reportedly preparing")
    assert parts[1].startswith("This is all according")
    assert parts[2].startswith("Finally, there's the notion")


def test_extract_x_article_url_from_metadata_urls():
    metadata = {
        "urls": [
            {"expanded_url": "http://x.com/i/article/2038460528033492992"},
        ]
    }
    assert _extract_x_article_url(metadata) == "https://x.com/i/article/2038460528033492992"


def test_title_looks_like_url_for_tco():
    assert _title_looks_like_url("https://t.co/J2ojwxpyBE")


def test_invalid_title_translation_for_refusal_text():
    original = "https://t.co/J2ojwxpyBE"
    candidate = "由于您没有提供需要翻译的具体内容，我无法进行翻译。"
    assert not _is_valid_title_translation(original, candidate)


def test_derive_title_from_body_skips_shortcut_noise():
    body = (
        "要查看键盘快捷键，按下问号\n"
        "查看键盘快捷键\n"
        "分享6个我觉得应该必装的Skills。\n"
        "@Khazix0918\n"
        "3小时\n"
    )
    assert _derive_title_from_body(body) == "分享6个我觉得应该必装的Skills。"
