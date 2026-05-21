"""Tests for listing summary boilerplate cleaning."""

from app.domains.ingest.summary_clean import clean_listing_summary


def test_clean_listing_summary_strips_verge_regulator_intro_en():
    raw = (
        "Hello and welcome to Regulator, a newsletter for Verge subscribers about tech and politics. "
        "If you're not a subscriber, sign up for our fine editorial enterprise today. "
        "And if you have any tips, send 'em over to tips@theverge.com. "
        "A quick note: Regulator will be on hiatus for the next two weeks while I take vacation."
    )
    assert clean_listing_summary(raw) == ""


def test_clean_listing_summary_strips_verge_regulator_intro_zh():
    raw = (
        "您好，欢迎来到《Regulator》！这是一份为Verge订阅者准备的通讯，主要报道华盛顿这个科技与政治交汇点。"
        "如果您还不是订阅用户，请立即注册我们的优质编辑刊物——尤其是在马斯克与阿尔特曼事件尘埃落定的时候。"
        "如果您有任何关于即将发生或隐藏的华盛顿交通事故的建议，请发送邮件至tips@theverge.com。"
        "温馨提示：《Regulator》将在接下来的两周内暂停更新……"
    )
    assert clean_listing_summary(raw) == ""


def test_clean_listing_summary_keeps_real_lede():
    raw = (
        "Hello and welcome to Regulator, a newsletter for Verge subscribers. "
        "Anthropic and OpenAI are taking their feud into the midterm elections via rival super PACs."
    )
    cleaned = clean_listing_summary(raw)
    assert "Anthropic and OpenAI" in cleaned
    assert "subscriber" not in cleaned.lower()
