import pytest
from fastapi import HTTPException

from app.api import sources as sources_api
from app.api.sources import _helpers as sources_helpers
from app.schemas.source import SourceCreate


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _DBStub:
    def __init__(self, total: int):
        self.total = total

    async def execute(self, _query):
        return _ScalarResult(self.total)


@pytest.mark.asyncio
async def test_source_quota_rejects_when_reaching_limit(monkeypatch):
    async def _fake_settings(_db):
        return {"limits": {"max_sources": 5}}

    monkeypatch.setattr(sources_helpers, "get_system_settings_async", _fake_settings)

    with pytest.raises(HTTPException) as exc:
        await sources_api._ensure_source_quota(_DBStub(total=5), incoming_count=1)

    assert exc.value.status_code == 409
    assert "上限" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_source_quota_allows_when_capacity_available(monkeypatch):
    async def _fake_settings(_db):
        return {"limits": {"max_sources": 5}}

    monkeypatch.setattr(sources_helpers, "get_system_settings_async", _fake_settings)

    await sources_api._ensure_source_quota(_DBStub(total=3), incoming_count=2)


def test_source_metadata_quality_fields_are_normalized():
    source = SourceCreate(
        name="AI Source",
        type="rss",
        url="https://example.com/feed.xml",
        metadata={
            "source_stars": "9",
            "source_weight": "1.9",
            "authority_type": "official_blog",
            "domain_focus": "AI, model\nsemiconductor",
        },
    )

    assert source.metadata_["source_stars"] == 3
    assert source.metadata_["source_weight"] == 1.5
    assert source.metadata_["authority_type"] == "official"
    assert source.metadata_["domain_focus"] == ["AI", "model", "semiconductor"]
