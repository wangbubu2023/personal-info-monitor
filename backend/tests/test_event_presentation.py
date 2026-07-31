from app.domains.events.presentation import (
    classify_event_section,
    is_rolling_highlight_event,
    simplify_event_name,
)


def test_single_source_cluster_stays_out_of_event_sections():
    assert classify_event_section(
        importance=70,
        incremental=72,
        confidence=92,
        corroboration_tier="single_high",
        independent_source_count=1,
    ) == "later"


def test_event_below_seventy_remains_brewing():
    assert classify_event_section(
        importance=69.9,
        incremental=72,
        confidence=92,
        corroboration_tier="single_high",
        independent_source_count=2,
    ) == "brewing"


def test_rolling_highlight_requires_heat_and_aggregation_but_not_hourly_increment():
    assert is_rolling_highlight_event(importance=70, independent_source_count=2) is True
    assert is_rolling_highlight_event(importance=69.9, independent_source_count=3) is False
    assert is_rolling_highlight_event(importance=95, independent_source_count=1) is False


def test_event_name_removes_article_framing_and_commentary():
    assert simplify_event_name("【早报】美股光通信、存储板块全线走强，中概股多数上涨") == (
        "美股光通信、存储板块全线走强，中概股多数上涨"
    )
    assert simplify_event_name("美伊对峙愈演愈烈？美军伤亡与日俱增，特朗普回应") == "美伊对峙升级"
    assert simplify_event_name("港股上行空间打开，机构称三大逻辑形成共振") == "港股上行空间打开"
    assert simplify_event_name("英伟达真正大敌！AMD首款机架级AI系统Helios收获微软采用") == (
        "AMD首款机架级AI系统Helios收获微软采用"
    )
    assert simplify_event_name("以全链条监管筑牢食品安全防线——第一批食品安全监管创新案例发布") == (
        "第一批食品安全监管创新案例发布"
    )


def test_long_event_name_is_bounded():
    value = simplify_event_name("苹果宣布面向多个市场推出新一代人工智能设备与配套软件服务计划")
    assert len(value) <= 28
