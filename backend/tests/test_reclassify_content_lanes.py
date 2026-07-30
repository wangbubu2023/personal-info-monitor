from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Content, Source
from app.models.source import SourceType
from scripts.reclassify_content_lanes import reclassify_content_lanes


def test_reclassify_content_lanes_updates_column_and_metadata(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'lane.db'}")
    Base.metadata.create_all(engine)
    sync_db = Session(engine)
    source = Source(name="Lane Source", type=SourceType.WEBSITE, url="https://lane.example.com")
    content = Content(
        source=source,
        title="OpenAI releases new frontier model",
        summary="The product update adds new reasoning capabilities.",
        full_content="OpenAI releases a new model for developers.",
        original_url="https://lane.example.com/model",
        content_type="website",
        lane="tech_product",
        metadata_={"lane": "tech_product", "article_score": 72.0},
    )
    sync_db.add(content)
    sync_db.flush()

    report = reclassify_content_lanes(sync_db)

    assert report["changed"] == 1
    assert report["lane_reclassified"] == 1
    assert report["storage_repaired"] == 0
    assert report["version_stamped"] == 0
    assert report["transitions"] == {"tech_product->product_news": 1}
    assert content.lane == "product_news"
    assert content.metadata_["lane"] == "product_news"
    assert content.metadata_["lane_classification_version"] == "pim-score-v2.3"
    assert content.metadata_["article_score"] == 72.0
    sync_db.close()
    engine.dispose()


def test_reclassify_content_lanes_repairs_column_metadata_drift(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'lane-drift.db'}")
    Base.metadata.create_all(engine)
    sync_db = Session(engine)
    source = Source(name="Lane Source", type=SourceType.WEBSITE, url="https://lane.example.com")
    content = Content(
        source=source,
        title="央行宣布降息",
        summary="货币政策进入新阶段。",
        original_url="https://lane.example.com/rates",
        content_type="website",
        lane="macro_finance",
        metadata_={
            "lane": "markets",
            "lane_classification_version": "pim-score-v2.3",
        },
    )
    sync_db.add(content)
    sync_db.flush()

    report = reclassify_content_lanes(sync_db)

    assert report["changed"] == 1
    assert report["lane_reclassified"] == 0
    assert report["storage_repaired"] == 1
    assert report["version_stamped"] == 0
    assert content.lane == "macro_finance"
    assert content.metadata_["lane"] == "macro_finance"
    sync_db.close()
    engine.dispose()
