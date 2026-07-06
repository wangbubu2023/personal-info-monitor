from __future__ import annotations

import os
import sqlite3
import subprocess
import sys


def test_fresh_sqlite_database_can_upgrade_to_head(tmp_path):
    data_dir = tmp_path / "pim-data"
    data_dir.mkdir()

    env = os.environ.copy()
    env["DATA_DIR"] = str(data_dir)
    env["_PIM_AI_DEPRECATION_LOGGED"] = "1"
    env.pop("DATABASE_URL", None)
    env.pop("ASYNC_DATABASE_URL", None)

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr

    db_path = data_dir / "pim.db"
    conn = sqlite3.connect(db_path)
    try:
        revision = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name IS NOT NULL"
            )
        }
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IS NOT NULL"
            )
        }
        score_feedback_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(score_feedback)")
        }
        content_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(contents)")
        }
        source_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(sources)")
        }
    finally:
        conn.close()

    assert revision == ("20260702_0026",)
    assert "ix_content_created_at" in indexes
    assert "ix_score_feedback_content_id" in indexes
    assert "ix_score_feedback_event_type" in indexes
    assert {"event_type", "event_value"} <= score_feedback_columns
    assert {"article_score", "final_score", "selection_status", "lane"} <= content_columns
    assert "ix_content_article_score" in indexes
    assert "ix_content_selection_status" in indexes
    assert "ix_content_lane" in indexes
    assert "source_fetch_log" in tables
    assert {
        "fetch_failure_code",
        "fetch_failure_status",
        "fetch_failure_severity",
        "fetch_failure_retryable",
        "fetch_failure_consecutive",
        "fetch_failure_updated_at",
        "fetch_cooldown_until",
        "rss_health_status",
        "rss_health_healthy",
        "rss_health_item_count",
        "rss_health_last_update",
        "rss_health_stale_days",
        "rss_health_reason",
        "rss_health_checked_at",
        "rss_health_feed_url",
        "discovery_checked_at",
        "discovery_total",
        "discovery_kept",
        "discovery_dropped_no_url",
        "discovery_dropped_off_domain",
        "discovery_dropped_deny",
        "discovery_dropped_allow_miss",
        "discovery_dropped_non_article_url",
        "discovery_dropped_short_title",
        "discovery_dropped_duplicate",
        "discovery_dropped_stale",
        "discovery_truncated",
        "discovery_listing_urls_configured",
        "discovery_listing_pages_total",
        "discovery_listing_pages_fetched",
        "discovery_listing_pages_failed",
        "discovery_pagination_max_pages",
        "last_fetch_outcome_code",
        "last_fetch_outcome_severity",
        "last_fetch_outcome_message",
        "last_fetch_outcome_updated_at",
        "session_health_status",
        "session_health_reason",
        "session_health_suggested_action",
        "session_health_validated_at",
        "session_health_details",
        "session_health_alert_reason",
        "session_health_alert_sent_at",
    } <= source_columns
    assert "ix_source_fetch_log_source_attempted" in indexes
    assert "ix_source_fetch_log_outcome" in indexes
    assert "ix_atoms_status" in indexes
    assert "ix_event_clusters_domain" in indexes
    assert "ix_knowledge_entities_canonical_name" in indexes
