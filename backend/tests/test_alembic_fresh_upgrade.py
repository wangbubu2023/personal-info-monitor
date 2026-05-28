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
    finally:
        conn.close()

    assert revision == ("20260522_0015",)
    assert "ix_content_created_at" in indexes
    assert "ix_score_feedback_content_id" in indexes
