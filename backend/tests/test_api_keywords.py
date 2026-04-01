from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_keyword_routes_are_disabled(client):
    response = await client.get("/api/keywords")
    assert response.status_code == 404
