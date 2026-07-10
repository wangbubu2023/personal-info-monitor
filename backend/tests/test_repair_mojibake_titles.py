from __future__ import annotations

import sqlite3
from contextlib import closing

from scripts.repair_mojibake_titles import apply_candidates, find_candidates, repair_title_losslessly


def test_repairs_latin1_decoded_utf8_chinese_title_losslessly():
    expected = "小米卢伟冰爆料 REDMI Note 17 标准版手机"
    mojibake = expected.encode("utf-8").decode("latin-1")

    assert repair_title_losslessly(mojibake) == (expected, "latin-1")


def test_does_not_touch_valid_or_already_lossy_titles():
    assert repair_title_losslessly("小米发布新手机") is None
    assert repair_title_losslessly("Café update") is None
    assert repair_title_losslessly("å°�米") is None


def test_finds_only_unedited_rss_rows_and_applies_compare_and_swap():
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.executescript(
            """
            CREATE TABLE sources (id TEXT PRIMARY KEY, name TEXT, type TEXT);
            CREATE TABLE contents (
              id TEXT PRIMARY KEY,
              source_id TEXT,
              external_id TEXT,
              title TEXT,
              is_user_edited INTEGER,
              created_at TEXT,
              updated_at TEXT
            );
            INSERT INTO sources VALUES ('rss', 'IT之家', 'RSS');
            INSERT INTO sources VALUES ('web', 'Example', 'WEBSITE');
            """
        )
        expected = "小米卢伟冰爆料"
        bad = expected.encode("utf-8").decode("latin-1")
        connection.executemany(
            "INSERT INTO contents VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            [
                ("repair", "rss", "entry-1", bad, 0),
                ("edited", "rss", "entry-2", bad, 1),
                ("website", "web", "entry-3", bad, 0),
            ],
        )

        candidates = find_candidates(connection)
        assert [item.content_id for item in candidates] == ["repair"]
        assert apply_candidates(connection, candidates) == 1
        assert connection.execute("SELECT title FROM contents WHERE id = 'repair'").fetchone()[0] == expected
        assert apply_candidates(connection, candidates) == 0
