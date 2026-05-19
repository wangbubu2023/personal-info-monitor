from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def stub_keyword_equivalents(monkeypatch):
    async def _fake_build_equivalent_terms(keyword: str, *, match_type: str = "contains") -> list[str]:
        mapping = {
            "AI": ["人工智能"],
            "Agent": ["智能体"],
            "OpenAI": ["开放人工智能"],
            "openai": ["开放人工智能"],
        }
        return mapping.get(keyword, [])

    monkeypatch.setattr("app.services.keyword_rules.build_equivalent_terms", _fake_build_equivalent_terms)


@pytest.fixture(autouse=True)
def noop_keyword_match_background_refresh(monkeypatch):
    """Async test DB is isolated; sync SessionLocal in refresh would hit a different DB."""
    async def _noop() -> None:
        return None

    monkeypatch.setattr("app.api.keywords._background_refresh_keyword_matches", _noop)


@pytest.mark.asyncio
async def test_keyword_routes_are_enabled(client):
    response = await client.get("/api/keywords")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_keyword_batch_create_supports_multiple_keywords(client):
    response = await client.post(
        "/api/keywords/batch",
        json={
            "keywords": ["AI", "OpenAI", "Agent"],
            "match_type": "contains",
            "match_scope": "title_content",
            "color": "#ff4d4f",
            "enabled": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert [item["keyword"] for item in data["items"]] == ["AI", "OpenAI", "Agent"]


@pytest.mark.asyncio
async def test_keyword_batch_create_filters_empty_and_duplicate_keywords(client):
    response = await client.post(
        "/api/keywords/batch",
        json={
            "keywords": ["AI", " ", "AI", "ai", "Agent"],
            "match_type": "contains",
            "color": "#ff4d4f",
            "enabled": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert [item["keyword"] for item in data["items"]] == ["AI", "Agent"]
    assert sorted(data["skipped_keywords"]) == ["AI", "ai"]


@pytest.mark.asyncio
async def test_keyword_create_rejects_duplicate_case_insensitive_with_message(client):
    first = await client.post(
        "/api/keywords",
        json={
            "keyword": "openclaw",
            "match_type": "contains",
            "color": "#ff4d4f",
        },
    )
    assert first.status_code == 200

    dup = await client.post(
        "/api/keywords",
        json={
            "keyword": "Openclaw",
            "match_type": "contains",
            "color": "#ff4d4f",
        },
    )
    assert dup.status_code == 409
    assert "忽略大小写" in dup.json()["detail"]


@pytest.mark.asyncio
async def test_keyword_batch_create_same_input_skips_case_variant(client):
    response = await client.post(
        "/api/keywords/batch",
        json={
            "keywords": ["openclaw", "Openclaw", "Agent"],
            "match_type": "contains",
            "match_scope": "title_content",
            "color": "#ff4d4f",
            "enabled": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert [item["keyword"] for item in data["items"]] == ["openclaw", "Agent"]
    assert "Openclaw" in data["skipped_keywords"]


@pytest.mark.asyncio
async def test_keyword_batch_create_skips_existing_keywords_case_insensitive(client):
    first = await client.post(
        "/api/keywords",
        json={
            "keyword": "OpenAI",
            "match_type": "contains",
            "color": "#ff4d4f",
        },
    )
    assert first.status_code == 200

    response = await client.post(
        "/api/keywords/batch",
        json={
            "keywords": ["openai", "Agent"],
            "match_type": "contains",
            "color": "#ff4d4f",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert [item["keyword"] for item in data["items"]] == ["Agent"]
    assert data["skipped_keywords"] == ["openai"]


@pytest.mark.asyncio
async def test_keyword_batch_update_changes_scope_and_color(client):
    created = await client.post(
        "/api/keywords/batch",
        json={
            "keywords": ["AI", "Agent"],
            "match_type": "contains",
            "match_scope": "title",
            "color": "#ff4d4f",
        },
    )
    assert created.status_code == 200
    item_ids = [item["id"] for item in created.json()["items"]]

    response = await client.patch(
        "/api/keywords/batch",
        json={
            "keyword_ids": item_ids,
            "match_scope": "content",
            "color": "#1677ff",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert all(item["match_scope"] == "content" for item in data["items"])
    assert all(item["color"] == "#1677ff" for item in data["items"])


@pytest.mark.asyncio
async def test_keyword_batch_update_match_type_and_enabled(client):
    created = await client.post(
        "/api/keywords/batch",
        json={
            "keywords": ["AI", "Agent"],
            "match_type": "contains",
            "match_scope": "title_content",
            "color": "#ff4d4f",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    item_ids = [item["id"] for item in created.json()["items"]]

    response = await client.patch(
        "/api/keywords/batch",
        json={
            "keyword_ids": item_ids,
            "match_type": "exact",
            "enabled": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert all(item["match_type"] == "exact" for item in data["items"])
    assert all(item["enabled"] is False for item in data["items"])


@pytest.mark.asyncio
async def test_keyword_create_respects_manual_equivalents_without_auto(client):
    response = await client.post(
        "/api/keywords",
        json={
            "keyword": "Meta",
            "match_type": "contains",
            "color": "#ff4d4f",
            "manual_equivalent_terms": ["元宇宙", "脸书"],
            "include_auto_equivalent_terms": False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["manual_equivalent_terms"] == ["元宇宙", "脸书"]
    assert data["include_auto_equivalent_terms"] is False
    assert data["equivalent_terms"] == ["元宇宙", "脸书"]


@pytest.mark.asyncio
async def test_patch_disable_include_auto_clears_auto_equivalents(client, monkeypatch):
    """仅关闭「合并自动翻译」时，等价词应只剩手动部分（此处为空则清空机翻如「纳米香蕉」）。"""

    async def _fake_build(keyword: str, *, match_type: str = "contains"):
        if "nano" in keyword.lower():
            return ["纳米香蕉"]
        return []

    monkeypatch.setattr("app.services.keyword_rules.build_equivalent_terms", _fake_build)

    created = await client.post(
        "/api/keywords",
        json={
            "keyword": "nano banana",
            "match_type": "contains",
            "color": "#ff4d4f",
            "include_auto_equivalent_terms": True,
        },
    )
    assert created.status_code == 200
    kid = created.json()["id"]
    assert "纳米香蕉" in created.json()["equivalent_terms"]

    patched = await client.patch(
        f"/api/keywords/{kid}",
        json={"include_auto_equivalent_terms": False},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["include_auto_equivalent_terms"] is False
    assert body["equivalent_terms"] == []

    listed = await client.get("/api/keywords")
    row = next(item for item in listed.json()["items"] if item["id"] == kid)
    assert row["equivalent_terms"] == []
    assert row["include_auto_equivalent_terms"] is False


@pytest.mark.asyncio
async def test_patch_manual_equivalent_merges_with_auto_list_and_response_match(client, monkeypatch):
    """编辑手动等价词后，合并结果应写入 PATCH 响应与 GET 列表（与「仍显示旧自动翻译」回归相关）。"""

    async def _fake_build(keyword: str, *, match_type: str = "contains"):
        if keyword.casefold() == "openclaw":
            return ["开爪"]
        return []

    monkeypatch.setattr("app.services.keyword_rules.build_equivalent_terms", _fake_build)

    created = await client.post(
        "/api/keywords",
        json={
            "keyword": "openclaw",
            "match_type": "contains",
            "color": "#ff4d4f",
            "include_auto_equivalent_terms": True,
        },
    )
    assert created.status_code == 200
    kid = created.json()["id"]
    assert "开爪" in created.json()["equivalent_terms"]

    patched = await client.patch(
        f"/api/keywords/{kid}",
        json={
            "manual_equivalent_terms": ["小龙虾"],
            "include_auto_equivalent_terms": True,
        },
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["manual_equivalent_terms"] == ["小龙虾"]
    assert "小龙虾" in body["equivalent_terms"]
    assert "开爪" in body["equivalent_terms"]

    listed = await client.get("/api/keywords")
    assert listed.status_code == 200
    row = next(item for item in listed.json()["items"] if item["id"] == kid)
    assert "小龙虾" in row["equivalent_terms"]
    assert "开爪" in row["equivalent_terms"]
