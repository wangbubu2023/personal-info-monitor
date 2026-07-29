from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.domains.fetch.collectors import website_shadow_dom


@pytest.mark.asyncio
async def test_shadow_dom_materialization_is_bounded_and_reports_trace(monkeypatch):
    monkeypatch.setattr(
        website_shadow_dom,
        "get_settings",
        lambda: SimpleNamespace(pim_web_clean_enabled=False, pim_web_clean_shadow=True),
    )
    page = SimpleNamespace(evaluate=AsyncMock(return_value={"count": 4, "timedOut": False, "nodes": 90, "chars": 5000}))
    logger = SimpleNamespace(debug=lambda *args: None)

    count, timed_out = await website_shadow_dom.materialize_shadow_dom(page, logger=logger)

    assert (count, timed_out) == (4, False)
    script, limits = page.evaluate.await_args.args
    assert "assignedNodes({flatten: true})" in script
    assert "duplicates visible article text" in script
    assert "getComputedStyle" in script
    assert "node.shadowRoot" in script
    assert limits["maxDepth"] == 12
    assert limits["maxNodes"] == 20_000
    assert limits["maxChars"] == 1_000_000


@pytest.mark.asyncio
async def test_shadow_dom_disabled_does_not_touch_page(monkeypatch):
    monkeypatch.setattr(
        website_shadow_dom,
        "get_settings",
        lambda: SimpleNamespace(pim_web_clean_enabled=False, pim_web_clean_shadow=False),
    )
    page = SimpleNamespace(evaluate=AsyncMock())

    assert await website_shadow_dom.materialize_shadow_dom(page, logger=SimpleNamespace(debug=lambda *args: None)) == (0, False)
    page.evaluate.assert_not_awaited()


@pytest.mark.asyncio
async def test_shadow_dom_timeout_stamps_diagnostic_marker(monkeypatch):
    monkeypatch.setattr(
        website_shadow_dom,
        "get_settings",
        lambda: SimpleNamespace(pim_web_clean_enabled=True, pim_web_clean_shadow=False),
    )
    page = SimpleNamespace(evaluate=AsyncMock(side_effect=[TimeoutError(), None]))
    logger = SimpleNamespace(debug=lambda *args: None)

    count, timed_out = await website_shadow_dom.materialize_shadow_dom(page, logger=logger)

    assert (count, timed_out) == (0, True)
    assert page.evaluate.await_count == 2
    assert "data-pim-shadow-timeout" in page.evaluate.await_args_list[1].args[0]


@pytest.mark.asyncio
async def test_shadow_dom_result_count_is_clamped(monkeypatch):
    monkeypatch.setattr(
        website_shadow_dom,
        "get_settings",
        lambda: SimpleNamespace(pim_web_clean_enabled=True, pim_web_clean_shadow=False),
    )
    page = SimpleNamespace(evaluate=AsyncMock(return_value={"count": 999999, "timedOut": False}))

    count, timed_out = await website_shadow_dom.materialize_shadow_dom(
        page,
        logger=SimpleNamespace(debug=lambda *args: None),
    )

    assert (count, timed_out) == (128, False)
