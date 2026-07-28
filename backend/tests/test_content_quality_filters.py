from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.contents import _build_low_signal_cleanup_report
from app.database import Base
from app.models import Content, Source
from app.models.source import SourceType
from app.domains.ingest.normalizer import NormalizerStage
from app.domains.ingest.quality import (
    get_non_article_format_reject_reason,
    get_website_content_reject_reason,
    is_rss_sourced_item,
)
from app.utils.datetime import utcnow_naive


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_website_content_gate_rejects_known_navigation_titles():
    assert (
        get_website_content_reject_reason(
            "https://hbr.org",
            {
                "title": "Subscribe",
                "content": "",
                "url": "https://hbr.org/subscribe",
            },
        )
        == "blocked_navigation_title"
    )
    assert (
        get_website_content_reject_reason(
            "https://hbr.org",
            {
                "title": "My Library",
                "content": "",
                "url": "https://hbr.org/my-library",
            },
        )
        == "blocked_navigation_title"
    )


def test_website_content_gate_rejects_hbr_and_bi_section_hubs():
    assert (
        get_website_content_reject_reason(
            "https://hbr.org",
            {
                "title": "Innovation",
                "content": "",
                "url": "https://hbr.org/topic/innovation",
            },
        )
        == "blocked_section_hub_title"
    )
    assert (
        get_website_content_reject_reason(
            "https://hbr.org",
            {
                "title": "Leadership",
                "content": "x" * 400,
                "url": "https://hbr.org/topic/leadership",
            },
        )
        == "blocked_section_hub_title"
    )
    assert (
        get_website_content_reject_reason(
            "https://hbr.org",
            {
                "title": "Managing Yourself",
                "content": "x" * 400,
                "url": "https://hbr.org/topic/managing-yourself",
            },
        )
        == "blocked_section_hub_title"
    )
    assert (
        get_website_content_reject_reason(
            "https://www.businessinsider.com",
            {
                "title": "Personal Finance",
                "content": "",
                "url": "https://www.businessinsider.com/personal-finance",
            },
        )
        == "blocked_section_hub_title"
    )
    assert (
        get_website_content_reject_reason(
            "https://www.businessinsider.com",
            {
                "title": "The Better Work Project",
                "content": "x" * 500,
                "url": "https://www.businessinsider.com/sc/introducing-the-better-work-project-hub",
            },
        )
        == "blocked_section_hub_title"
    )


def test_website_content_gate_rejects_bi_show_and_guide_paths_with_thin_text():
    assert (
        get_website_content_reject_reason(
            "https://www.businessinsider.com/tech",
            {
                "title": "How Crime Works",
                "content": "",
                "url": "https://www.businessinsider.com/show/how-crime-works",
            },
        )
        == "blocked_domain_non_article_path"
    )
    assert (
        get_website_content_reject_reason(
            "https://www.businessinsider.com/tech",
            {
                "title": "Best Apple Watch in 2026",
                "content": "",
                "url": "https://www.businessinsider.com/guides/tech/best-apple-watch",
            },
        )
        == "blocked_domain_non_article_path"
    )


def test_website_content_gate_rejects_nav_titles_with_brand_suffix():
    assert (
        get_website_content_reject_reason(
            "https://hbr.org",
            {
                "title": "My Library - HBR",
                "content": "x" * 500,
                "url": "https://hbr.org/my-library",
            },
        )
        == "blocked_navigation_title"
    )
    assert (
        get_website_content_reject_reason(
            "https://hbr.org",
            {
                "title": "HBR | Subscribe",
                "content": "x" * 500,
                "url": "https://hbr.org/subscriptions",
            },
        )
        == "blocked_navigation_title"
    )


def test_website_content_gate_keeps_article_like_urls():
    assert (
        get_website_content_reject_reason(
            "https://hbr.org",
            {
                "title": "How AI Changes Team Strategy",
                "content": "",
                "url": "https://hbr.org/2026/03/how-ai-changes-team-strategy",
            },
        )
        is None
    )
    assert (
        get_website_content_reject_reason(
            "https://www.businessinsider.com",
            {
                "title": "Retailers rethink pricing after new tariff plan",
                "content": "",
                "url": "https://www.businessinsider.com/retailers-rethink-pricing-after-new-tariff-plan-2026-3",
            },
        )
        is None
    )


def test_non_article_format_rejects_nyt_slideshow_even_from_rss():
    raw = {
        "title": "图集：图片中的2025年（下）",
        "content": "",
        "url": "https://cn.nytimes.com/slideshow/20251229/year-in-pictures-2025-2/",
        "ingest_channel": "rss",
        "metadata": {"ingest_channel": "rss"},
    }
    assert (
        get_non_article_format_reject_reason("https://cn.nytimes.com/", raw)
        == "blocked_non_article_format"
    )
    assert get_website_content_reject_reason("https://cn.nytimes.com/", raw) is None


def test_non_article_format_rejects_engadget_science_news_roundup():
    raw = {
        "title": "Perseverance checks in from Mars with a selfie, and more science stories",
        "content": "",
        "url": "https://www.engadget.com/2174445/perseverance-mars-selfie-science-news/",
        "ingest_channel": "rss",
    }
    assert (
        get_non_article_format_reject_reason("https://www.engadget.com/", raw)
        == "blocked_engadget_roundup"
    )


def test_non_article_format_rejects_engadget_review_recap():
    raw = {
        "title": "Engadget review recap: Razr Fold, Bose Lifestyle Ultra Speaker and more",
        "content": "x" * 500,
        "url": "https://www.engadget.com/2174499/engadget-review-recap-razr-fold/",
        "ingest_channel": "rss",
    }
    assert (
        get_non_article_format_reject_reason("https://www.engadget.com/", raw)
        == "blocked_engadget_roundup"
    )
    assert get_website_content_reject_reason("https://www.engadget.com/", raw) is None


@pytest.mark.parametrize(
    ("title", "url"),
    [
        ("30% Off Samsung Promo Code | July 2026", "https://www.wired.com/story/samsung-promo-codes/"),
        ("Newegg Promo Codes and Coupons for July 2026", "https://www.wired.com/story/newegg-promo-code/"),
        ("Altra Running Promo Codes: 10% Off July 2026", "https://www.wired.com/story/altra-promo-code/"),
        ("Herman Miller Promo Codes: 40% Off July 2026", "https://www.wired.com/story/herman-miller-promo-code/"),
        ("25% Off Adidas Promo Code | July 2026", "https://www.wired.com/story/adidas-promo-code/"),
        ("Uber Eats Promo Codes: $15 Off│July 2026", "https://www.wired.com/story/uber-eats-promo-code/"),
        ("Ray-Ban Promo Codes: Save 50% in July 2026", "https://www.wired.com/story/ray-ban-promo-code/"),
        ("Ulta Promo Codes: Up to 50% Off in July 2026", "https://www.wired.com/story/ulta-coupon/"),
        ("B&H Photo Promo Codes and Deals This July 2026", "https://www.wired.com/story/bh-photo-coupon/"),
        ("Birdfy Discount Codes: 15% Off Sitewide", "https://www.wired.com/story/birdfy-discount-code/"),
        ("Corsair Discount Code: Up to 50% Off for July 2026", "https://www.wired.com/story/corsair-coupon/"),
    ],
)
def test_non_article_format_rejects_wired_coupon_landing_pages(title, url):
    raw = {
        "title": title,
        "content": "Long affiliate landing-page copy.",
        "url": url,
        "ingest_channel": "rss",
        "metadata": {"tags": ["Gear", "Shopping", "Coupons"], "ingest_channel": "rss"},
    }
    assert (
        get_non_article_format_reject_reason("https://www.wired.com/feed/rss", raw)
        == "blocked_promotional_coupon_page"
    )


def test_non_article_format_keeps_reporting_about_promo_code_changes():
    raw = {
        "title": "Retailer disables leaked promo codes after account breach",
        "content": "The company said the codes were disabled during its security response.",
        "url": "https://example.com/news/leaked-promo-codes-disabled",
        "ingest_channel": "rss",
        "metadata": {"tags": ["Security", "News"], "ingest_channel": "rss"},
    }
    assert get_non_article_format_reject_reason("https://example.com/feed", raw) is None


async def test_normalizer_stage_drops_coupon_landing_page_from_rss(db_session):
    db = db_session
    source = Source(
        name="Wired",
        type=SourceType.RSS,
        url="https://www.wired.com/feed/rss",
        fetch_interval=60,
        enabled=True,
        metadata_={},
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    raw_contents = [
        {
            "external_id": "https://www.wired.com/story/samsung-promo-codes/",
            "title": "30% Off Samsung Promo Code | July 2026",
            "content": "Long affiliate landing-page copy.",
            "url": "https://www.wired.com/story/samsung-promo-codes/",
            "publish_time": utcnow_naive(),
            "ingest_channel": "rss",
            "metadata": {"tags": ["Gear", "Shopping", "Coupons"], "ingest_channel": "rss"},
        },
    ]
    diagnostics = []

    valid_contents, stale_skipped = await NormalizerStage.execute(
        db=db,
        source=source,
        raw_contents=raw_contents,
        manual_trigger=False,
        diagnostics=diagnostics,
    )

    assert stale_skipped == 0
    assert valid_contents == []
    assert diagnostics == [
        {
            "reason": "non_article_format",
            "detail": "blocked_promotional_coupon_page",
            "title": "30% Off Samsung Promo Code | July 2026",
            "url": "https://www.wired.com/story/samsung-promo-codes/",
        }
    ]


async def test_normalizer_stage_drops_engadget_roundup_from_rss(db_session):
    db = db_session
    source = Source(
        name="Engadget",
        type=SourceType.WEBSITE,
        url="https://www.engadget.com/",
        fetch_interval=60,
        enabled=True,
        metadata_={},
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    now = utcnow_naive()
    raw_contents = [
        {
            "external_id": "https://www.engadget.com/2174445/foo-science-news/",
            "title": "Mars selfie, satellite pollution, and more science stories",
            "content": "",
            "url": "https://www.engadget.com/2174445/foo-science-news/",
            "publish_time": now,
            "ingest_channel": "rss",
            "metadata": {"ingest_channel": "rss"},
        },
    ]

    valid_contents, stale_skipped = await NormalizerStage.execute(
        db=db,
        source=source,
        raw_contents=raw_contents,
        manual_trigger=False,
    )

    assert stale_skipped == 0
    assert valid_contents == []


async def test_normalizer_stage_drops_rss_sourced_slideshow_items(db_session):
    db = db_session
    source = Source(
        name="NYT CN",
        type=SourceType.WEBSITE,
        url="https://cn.nytimes.com/",
        fetch_interval=60,
        enabled=True,
        metadata_={},
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    now = utcnow_naive()
    raw_contents = [
        {
            "external_id": "https://cn.nytimes.com/slideshow/20251229/year-in-pictures-2025-2/",
            "title": "图集：图片中的2025年（下）",
            "content": "",
            "url": "https://cn.nytimes.com/slideshow/20251229/year-in-pictures-2025-2/",
            "publish_time": now,
            "ingest_channel": "rss",
            "metadata": {"ingest_channel": "rss"},
        },
    ]

    valid_contents, stale_skipped = await NormalizerStage.execute(
        db=db,
        source=source,
        raw_contents=raw_contents,
        manual_trigger=False,
    )

    assert stale_skipped == 0
    assert valid_contents == []


def test_rss_sourced_item_detected_from_ingest_channel():
    raw = {
        "title": "黑客军团如何渗透美国电网",
        "content": "x" * 77,
        "url": "https://cn.nytimes.com/china/2026/05/20/hackers-power-grid/",
        "ingest_channel": "rss",
    }
    assert is_rss_sourced_item(raw)
    assert (
        get_website_content_reject_reason("https://cn.nytimes.com/", raw)
        == "low_content_single_phrase_link"
    )


async def test_normalizer_stage_keeps_rss_sourced_short_website_items(db_session):
    db = db_session
    source = Source(
        name="NYT CN",
        type=SourceType.WEBSITE,
        url="https://cn.nytimes.com/",
        fetch_interval=60,
        enabled=True,
        metadata_={},
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    now = utcnow_naive()
    raw_contents = [
        {
            "external_id": "https://cn.nytimes.com/china/2026/05/20/hackers-power-grid/",
            "title": "黑客军团如何渗透美国电网",
            "content": "x" * 77,
            "url": "https://cn.nytimes.com/china/2026/05/20/hackers-power-grid/",
            "publish_time": now,
            "ingest_channel": "rss",
            "metadata": {"ingest_channel": "rss"},
        },
    ]

    valid_contents, stale_skipped = await NormalizerStage.execute(
        db=db,
        source=source,
        raw_contents=raw_contents,
        manual_trigger=False,
    )

    assert stale_skipped == 0
    assert len(valid_contents) == 1
    assert valid_contents[0]["title"] == "黑客军团如何渗透美国电网"


async def test_normalizer_stage_keeps_low_signal_website_for_finish_acceptance(db_session):
    db = db_session
    source = Source(
        name="HBR",
        type=SourceType.WEBSITE,
        url="https://hbr.org",
        fetch_interval=60,
        enabled=True,
        metadata_={},
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    now = utcnow_naive()
    raw_contents = [
        {
            "external_id": "https://hbr.org/topic/innovation",
            "title": "Innovation",
            "content": "",
            "url": "https://hbr.org/topic/innovation",
            "publish_time": now,
        },
        {
            "external_id": "https://hbr.org/subscribe",
            "title": "Subscribe",
            "content": "",
            "url": "https://hbr.org/subscribe",
            "publish_time": now,
        },
        {
            "external_id": "https://hbr.org/2026/03/how-ai-changes-team-strategy",
            "title": "How AI Changes Team Strategy",
            "content": "",
            "url": "https://hbr.org/2026/03/how-ai-changes-team-strategy",
            "publish_time": now,
        },
        {
            "external_id": "https://hbr.org/slideshow/team-photos",
            "title": "Photo gallery: team photos",
            "content": "",
            "url": "https://hbr.org/slideshow/team-photos",
            "publish_time": now,
        },
    ]

    valid_contents, stale_skipped = await NormalizerStage.execute(
        db=db,
        source=source,
        raw_contents=raw_contents,
        manual_trigger=False,
    )

    assert stale_skipped == 0
    assert [item["title"] for item in valid_contents] == [
        "Innovation",
        "Subscribe",
        "How AI Changes Team Strategy",
    ]


async def test_normalizer_stage_keeps_cross_source_external_id_matches(db_session):
    db = db_session
    source_a = Source(
        name="X Account A",
        type=SourceType.X,
        url="https://x.com/account-a",
        fetch_interval=60,
        enabled=True,
        metadata_={},
    )
    source_b = Source(
        name="X Account B",
        type=SourceType.X,
        url="https://x.com/account-b",
        fetch_interval=60,
        enabled=True,
        metadata_={},
    )
    db.add(source_a)
    db.add(source_b)
    db.commit()
    db.refresh(source_a)
    db.refresh(source_b)

    existing = Content(
        source_id=source_a.id,
        external_id="tweet-123",
        title="Existing title",
        summary="existing summary",
        original_url="https://x.com/account-a/status/123",
        content_type="x",
        publish_time=utcnow_naive(),
    )
    db.add(existing)
    db.commit()
    db.refresh(existing)

    now = utcnow_naive()
    raw_contents = [
        {
            "external_id": "tweet-123",
            "title": "Forwarded title",
            "content": "hello",
            "url": "https://x.com/account-b/status/123",
            "publish_time": now,
            "metadata": {},
        },
    ]

    valid_contents, stale_skipped = await NormalizerStage.execute(
        db=db,
        source=source_b,
        raw_contents=raw_contents,
        manual_trigger=False,
    )

    assert stale_skipped == 0
    assert len(valid_contents) == 1
    assert valid_contents[0]["external_id"] == "tweet-123"
    assert valid_contents[0]["metadata"]["cross_source_external_id_match"] == existing.id


async def test_normalizer_scheduled_allows_days_old_website_rss_items_by_default(db_session):
    """Regression: 60m default lag dropped entire VentureBeat-style RSS-backed website feeds."""
    db = db_session
    source = Source(
        name="VB",
        type=SourceType.WEBSITE,
        url="https://venturebeat.com/",
        fetch_interval=60,
        enabled=True,
        metadata_={},
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    old = utcnow_naive() - timedelta(days=2)
    raw_contents = [
        {
            "external_id": "vb-1",
            "title": "Some enterprise AI story",
            "content": "x" * 300,
            "url": "https://venturebeat.com/ai/some-enterprise-ai-story-2026",
            "publish_time": old,
        },
    ]

    valid_contents, stale_skipped = await NormalizerStage.execute(
        db=db,
        source=source,
        raw_contents=raw_contents,
        manual_trigger=False,
    )

    assert stale_skipped == 0
    assert len(valid_contents) == 1


async def test_normalizer_scheduled_keeps_tight_lag_for_x_by_default(db_session):
    db = db_session
    source = Source(
        name="X user",
        type=SourceType.X,
        url="https://x.com/example",
        fetch_interval=60,
        enabled=True,
        metadata_={},
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    old = utcnow_naive() - timedelta(hours=3)
    raw_contents = [
        {
            "external_id": "tweet-999",
            "title": "Old post",
            "content": "hello world " * 20,
            "url": "https://x.com/example/status/999",
            "publish_time": old,
        },
    ]

    valid_contents, stale_skipped = await NormalizerStage.execute(
        db=db,
        source=source,
        raw_contents=raw_contents,
        manual_trigger=False,
    )

    assert stale_skipped == 1
    assert valid_contents == []


async def test_normalizer_scheduled_x_lag_scales_with_fetch_interval(db_session):
    db = db_session
    source = Source(
        name="X slower user",
        type=SourceType.X,
        url="https://x.com/example",
        fetch_interval=120,
        enabled=True,
        metadata_={},
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    old = utcnow_naive() - timedelta(hours=3)
    raw_contents = [
        {
            "external_id": "tweet-1000",
            "title": "Still in scheduled window",
            "content": "hello world " * 20,
            "url": "https://x.com/example/status/1000",
            "publish_time": old,
        },
    ]

    valid_contents, stale_skipped = await NormalizerStage.execute(
        db=db,
        source=source,
        raw_contents=raw_contents,
        manual_trigger=False,
    )

    assert stale_skipped == 0
    assert len(valid_contents) == 1


def test_low_signal_cleanup_report_matches_only_junk_history():
    now = utcnow_naive()
    source = Source(
        id="source-1",
        name="BI",
        type=SourceType.WEBSITE,
        url="https://www.businessinsider.com",
        metadata_={},
    )
    junk = Content(
        id="content-1",
        source_id=source.id,
        source=source,
        title="Personal Finance",
        original_url="https://www.businessinsider.com/personal-finance",
        content_type="website",
        summary="",
        full_content="",
        publish_time=now,
    )
    article = Content(
        id="content-2",
        source_id=source.id,
        source=source,
        title="Retailers rethink pricing after new tariff plan",
        original_url="https://www.businessinsider.com/retailers-rethink-pricing-after-new-tariff-plan-2026-3",
        content_type="website",
        summary="",
        full_content="",
        publish_time=now,
    )

    matched, report = _build_low_signal_cleanup_report([junk, article], preview_limit=10)

    assert [item.id for item in matched] == ["content-1"]
    assert report["matched_count"] == 1
    assert report["by_reason"] == {"blocked_section_hub_title": 1}
    assert report["by_source"] == {"BI": 1}
    assert report["preview"][0]["title"] == "Personal Finance"
