from uuid import uuid4

import pytest

from app.domains.ingest.content_processor import ContentProcessor


class _SourceStub:
    def __init__(self, source_type: str = "website"):
        self.id = str(uuid4())
        self.url = "https://example.com/article"
        self.type = source_type
        self._runtime_auth = {}


@pytest.mark.asyncio
async def test_content_processor_process_is_llm_free(monkeypatch):
    processor = ContentProcessor()
    source = _SourceStub()

    async def _boom(*args, **kwargs):
        raise AssertionError("LLM call should not happen in fetch processing path")

    monkeypatch.setattr(processor.summarizer, "summarize", _boom)
    monkeypatch.setattr(processor.translator, "translate", _boom)
    monkeypatch.setattr(processor.translator, "is_chinese", lambda _text: False)

    content = await processor.process(
        raw_content={
            "title": "Example Long Article",
            "url": "https://example.com/article",
            "content": "A" * 1800,
            "publish_time": "2026-03-30T00:00:00Z",
        },
        source=source,
        keywords=[],
        generate_summary=True,
        translate=True,
    )

    assert content.summary is not None
    assert content.translated_title is None
    assert content.translated_summary is None
