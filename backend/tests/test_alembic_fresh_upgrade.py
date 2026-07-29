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
        content_event_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(content_events)")
        }
        content_event_membership_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(content_event_memberships)")
        }
        content_event_snapshot_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(content_event_snapshots)")
        }
        interaction_event_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(interaction_events)")
        }
        personal_item_state_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(personal_item_states)")
        }
        observation_aggregate_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(observation_aggregates)")
        }
        user_rule_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(user_rules)")
        }
        quality_adjudication_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(quality_adjudications)")
        }
        brief_snapshot_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(brief_snapshots)")
        }
    finally:
        conn.close()

    assert revision == ("20260729_0039",)
    assert "uq_local_capture_task_token_hash" in indexes
    assert {"modality_violation_count", "publication_status"} <= brief_snapshot_columns
    assert {
        "paid_source_matrix_audits",
        "session_recovery_audits",
        "local_capture_audits",
        "daily_canary_runs",
        "auth_archive_extractions",
        "topics",
        "topic_event_associations",
        "brief_snapshots",
        "modality_audit_logs",
    } <= tables


    assert "ix_score_feedback_event_type" in indexes
    assert {"event_type", "event_value"} <= score_feedback_columns
    assert {
        "article_score",
        "final_score",
        "selection_status",
        "lane",
        "is_duplicate",
        "duplicate_of",
    } <= content_columns
    assert "ix_content_article_score" in indexes
    assert "ix_content_selection_status" in indexes
    assert "ix_content_lane" in indexes
    assert "ix_content_is_duplicate" in indexes
    assert "ix_content_duplicate_of" in indexes
    assert "ix_contents_dup_group_id" in indexes
    assert "source_fetch_log" in tables
    assert {
        "auth_assistant_pairing_tokens",
        "auth_assistant_devices",
        "auth_assistant_import_logs",
    } <= tables
    assert "ix_auth_assistant_pairing_tokens_token_hash" in indexes
    assert "ix_auth_assistant_devices_token_hash" in indexes
    assert "ix_auth_assistant_import_logs_device_id" in indexes
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
    assert {
        "content_events",
        "content_event_memberships",
        "content_event_snapshots",
        "event_signatures",
        "event_assignment_logs",
        "event_rebalance_runs",
        "event_rebalance_suggestions",
        "event_today_diff_audits",
    } <= tables
    assert {
        "event_id",
        "event_key",
        "importance_score",
        "incremental_score",
        "confidence_score",
        "independent_source_count",
        "cluster_version",
        "latest_snapshot_version",
        "event_state",
        "canonical_content_id",
        "centroid",
        "dispersion",
        "last_material_update_at",
        "metadata",
    } <= content_event_columns
    assert {"event_id", "content_id", "role", "confidence", "evidence"} <= content_event_membership_columns
    assert {
        "event_id",
        "version",
        "what_changed",
        "why_matters",
        "source_content_ids",
        "change_type",
        "change_fingerprint",
        "facts",
        "evidence_refs",
        "uncertainty",
        "generator_version",
        "explanation",
    } <= content_event_snapshot_columns
    assert "ix_content_events_event_key" in indexes
    assert "ix_content_event_memberships_content" in indexes
    assert "ix_content_event_snapshots_event" in indexes
    assert {
        "interaction_events",
        "personal_item_states",
        "observation_aggregates",
        "user_rules",
    } <= tables
    assert {"target_type", "target_id", "action", "content_id", "event_id", "scope_type", "scope_key"} <= interaction_event_columns
    assert {"target_type", "target_id", "last_seen_version", "saved", "read_later", "hidden", "read_at"} <= personal_item_state_columns
    assert {"scope_type", "scope_key", "positive_evidence_count", "negative_evidence_count", "suggestion_status", "suggested_rule"} <= observation_aggregate_columns
    assert {"scope_type", "scope_key", "rule", "status", "created_by"} <= user_rule_columns
    assert "ix_interaction_events_target" in indexes
    assert "ix_personal_item_states_target" in indexes
    assert "ix_observation_aggregates_status" in indexes
    assert "ix_user_rules_scope" in indexes
    assert "quality_adjudications" in tables
    assert {
        "feedback_id",
        "issue_type",
        "status",
        "verdict",
        "adjudicator",
        "rationale",
        "gold_candidate",
        "hard_negative",
        "evidence",
    } <= quality_adjudication_columns
    assert "ix_quality_adjudications_issue_status" in indexes
    assert {"fetch_jobs", "bootstrap_codes", "web_sessions"} <= tables
    assert {
        "ix_fetch_jobs_source_id",
        "ix_fetch_jobs_state_not_before",
        "ix_bootstrap_codes_hash",
        "ix_web_sessions_token_hash",
        "ix_web_sessions_expires",
    } <= indexes
