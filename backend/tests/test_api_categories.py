from __future__ import annotations

import pytest

from app.models import Category, Source
from app.models.source import SourceType


@pytest.mark.asyncio
async def test_list_categories_uses_aggregated_source_counts(client, db_session):
    root = Category(name="Root", color="#111111")
    child = Category(name="Child", color="#222222", parent=root)
    db_session.add_all(
        [
            root,
            child,
            Source(name="Site A", type=SourceType.WEBSITE, url="https://a.example.com", category=root),
            Source(name="Site B", type=SourceType.RSS, url="https://b.example.com/rss", category=root),
            Source(name="Site C", type=SourceType.WEBSITE, url="https://c.example.com", category=child),
        ]
    )
    await db_session.commit()

    response = await client.get("/api/categories")
    assert response.status_code == 200
    payload = response.json()

    assert len(payload) == 1
    assert payload[0]["name"] == "Root"
    assert payload[0]["source_count"] == 2
    assert payload[0]["children"][0]["name"] == "Child"
    assert payload[0]["children"][0]["source_count"] == 1

    # Second request exercises the short-lived cache path.
    cached_response = await client.get("/api/categories")
    assert cached_response.status_code == 200
    assert cached_response.json()[0]["source_count"] == 2


@pytest.mark.asyncio
async def test_get_category_includes_child_counts_without_nested_queries(client, db_session):
    parent = Category(name="Parent", color="#333333")
    child_one = Category(name="Child 1", color="#444444", parent=parent)
    child_two = Category(name="Child 2", color="#555555", parent=parent)
    db_session.add_all(
        [
            parent,
            child_one,
            child_two,
            Source(name="Alpha", type=SourceType.WEBSITE, url="https://alpha.example.com", category=child_one),
            Source(name="Beta", type=SourceType.WEBSITE, url="https://beta.example.com", category=child_two),
        ]
    )
    await db_session.commit()

    response = await client.get(f"/api/categories/{parent.id}")
    assert response.status_code == 200
    payload = response.json()

    child_counts = {child["name"]: child["source_count"] for child in payload["children"]}
    assert child_counts == {"Child 1": 1, "Child 2": 1}
