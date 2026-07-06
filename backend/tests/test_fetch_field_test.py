from __future__ import annotations

from pathlib import Path

from scripts.run_fetch_field_test import render_markdown_report, run_field_test, write_outputs


def test_run_field_test_collects_dry_run_rows_and_keeps_failures():
    calls = []
    sources = {
        "items": [
            {"id": "source-1", "name": "Alpha", "type": "rss", "enabled": True},
            {"id": "source-2", "name": "Beta", "type": "website", "enabled": True},
        ]
    }

    def fake_request(method, path, api_key, params=None):
        calls.append((method, path, api_key, params))
        if path == "/api/sources":
            return sources
        if path == "/api/sources/source-1/dry-run":
            return {
                "source_id": "source-1",
                "source_name": "Alpha",
                "source_type": "rss",
                "warnings": {"merged": None, "primary": None},
                "stages": {
                    "collector": {"count": 3},
                    "normalizer": {"valid_count": 2},
                    "builder": {"would_store_count": 2},
                },
                "samples": {"would_store": [{"title": "Story A"}, {"title": "Story B"}]},
            }
        raise RuntimeError("site blocked")

    result = run_field_test(
        server="http://testserver",
        api_key="secret",
        limit=20,
        sample_limit=4,
        request_fn=fake_request,
    )

    assert calls[0] == ("GET", "/api/sources", "secret", {"enabled": "true", "page": 1, "page_size": 20})
    assert calls[1] == ("POST", "/api/sources/source-1/dry-run", "secret", {"sample_limit": 4})
    assert calls[2] == ("POST", "/api/sources/source-2/dry-run", "secret", {"sample_limit": 4})
    assert result["summary"] == {
        "total": 2,
        "ok": 1,
        "warning": 0,
        "empty": 0,
        "error": 1,
        "would_store_total": 2,
    }
    assert result["rows"][0]["samples"] == ["Story A", "Story B"]
    assert result["rows"][1]["status"] == "error"
    assert "site blocked" in result["rows"][1]["error"]


def test_run_field_test_filters_explicit_source_ids_with_full_page_size():
    def fake_request(method, path, _api_key, params=None):
        if path == "/api/sources":
            assert params == {"enabled": "true", "page": 1, "page_size": 200}
            return {
                "items": [
                    {"id": "source-1", "name": "Alpha", "type": "rss", "enabled": True},
                    {"id": "source-2", "name": "Beta", "type": "rss", "enabled": True},
                ]
            }
        assert method == "POST"
        return {
            "stages": {
                "collector": {"count": 0},
                "normalizer": {"valid_count": 0},
                "builder": {"would_store_count": 0},
            }
        }

    result = run_field_test(
        server="http://testserver",
        api_key="secret",
        source_ids=["source-2"],
        request_fn=fake_request,
    )

    assert [row["source_id"] for row in result["rows"]] == ["source-2"]


def test_run_field_test_filters_source_types_with_full_page_size():
    def fake_request(method, path, _api_key, params=None):
        if path == "/api/sources":
            assert params == {"enabled": "true", "page": 1, "page_size": 200}
            return {
                "items": [
                    {"id": "source-1", "name": "Alpha", "type": "rss", "enabled": True},
                    {"id": "source-2", "name": "Beta", "type": "x", "enabled": True},
                    {"id": "source-3", "name": "Gamma", "type": "website", "enabled": True},
                ]
            }
        assert method == "POST"
        return {
            "stages": {
                "collector": {"count": 1},
                "normalizer": {"valid_count": 1},
                "builder": {"would_store_count": 1},
            }
        }

    result = run_field_test(
        server="http://testserver",
        api_key="secret",
        source_types=["website", "rss"],
        exclude_types=["rss"],
        request_fn=fake_request,
    )

    assert [row["source_id"] for row in result["rows"]] == ["source-3"]


def test_run_field_test_surfaces_normalizer_skip_diagnostics():
    def fake_request(method, path, _api_key, params=None):
        if path == "/api/sources":
            return {"items": [{"id": "source-1", "name": "Dupe Feed", "type": "website", "enabled": True}]}
        assert method == "POST"
        return {
            "warnings": {"merged": None, "primary": None},
            "stages": {
                "collector": {"count": 2},
                "normalizer": {"valid_count": 0, "stale_skipped": 0, "other_skipped": 2},
                "builder": {"would_store_count": 0},
            },
            "samples": {"raw": [{"title": "Already Seen"}, {"title": "Also Seen"}], "would_store": []},
            "diagnostics": {"normalizer_skip_summary": {"duplicate_external_id": 2}},
        }

    result = run_field_test(
        server="http://testserver",
        api_key="secret",
        request_fn=fake_request,
    )

    row = result["rows"][0]
    assert row["status"] == "warning"
    assert row["warning"] == "normalizer skipped all items (duplicate_external_id=2)"
    assert row["samples"] == ["Already Seen", "Also Seen"]


def test_render_and_write_field_test_report(tmp_path: Path):
    result = {
        "ran_at": "2026-07-03T10:00:00+00:00",
        "server": "http://testserver",
        "summary": {"total": 1, "ok": 1, "warning": 0, "empty": 0, "error": 0, "would_store_total": 2},
        "rows": [
            {
                "source_id": "source-1",
                "source_name": "Alpha | Feed",
                "source_type": "rss",
                "status": "ok",
                "collected": 3,
                "valid": 2,
                "would_store": 2,
                "warning": "",
                "error": "",
                "samples": ["Story A"],
            }
        ],
    }

    markdown = render_markdown_report(result)
    assert "# PIM 20-Source Fetch Field Test" in markdown
    assert "Alpha \\| Feed" in markdown
    assert "Story A" in markdown

    report_path = tmp_path / "report.md"
    json_path = tmp_path / "report.json"
    write_outputs(result, report_path=report_path, json_path=json_path)

    assert report_path.read_text(encoding="utf-8") == markdown
    assert '"would_store_total": 2' in json_path.read_text(encoding="utf-8")
