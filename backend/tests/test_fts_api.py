import pytest
from httpx import AsyncClient

from app.models import Content, Source
from app.models.source import SourceType


@pytest.mark.asyncio
async def test_fts_search_api(client: AsyncClient):
    response = await client.get("/api/contents", params={"search": "test", "page_size": 1})
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_fts_empty_search(client: AsyncClient):
    response = await client.get("/api/contents", params={"page_size": 1})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_search_finds_cjk_substring_in_title(client: AsyncClient, db_session):
    """ILIKE 回退应能命中中文标题（不依赖 FTS5 分词）。"""
    src = Source(name="t", type=SourceType.RSS, url="https://example.com/feed")
    db_session.add(src)
    await db_session.flush()
    db_session.add(
        Content(
            source_id=src.id,
            title="关于特朗普的新闻",
            original_url="https://example.com/a",
            content_type="rss",
        )
    )
    await db_session.commit()

    r = await client.get("/api/contents", params={"search": "特朗普", "page_size": 10})
    assert r.status_code == 200
    assert r.json()["total"] >= 1
