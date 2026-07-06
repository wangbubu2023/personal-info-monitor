from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cli.pimctl.app import handle_sources


class _FakeClient:
    server = "http://testserver"

    def __init__(self):
        self.calls = []

    def request(self, method, path, *, params=None, json_body=None, auth_required=True):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "params": params,
                "json_body": json_body,
                "auth_required": auth_required,
            }
        )
        return {
            "source_name": "Dry Run Feed",
            "source_type": "rss",
            "dry_run": True,
            "would_write": False,
            "warnings": {"merged": None, "primary": None},
            "stages": {
                "collector": {"count": 2},
                "normalizer": {"valid_count": 1, "stale_skipped": 1, "other_skipped": 0},
                "builder": {"would_store_count": 1, "build_failed": 0},
            },
            "samples": {
                "would_store": [
                    {
                        "title": "Example",
                        "url": "https://example.com/a",
                        "external_id": "ext-1",
                        "full_content_chars": 123,
                    }
                ]
            },
        }


def test_sources_dry_run_cli_calls_endpoint(capsys):
    client = _FakeClient()
    args = SimpleNamespace(
        command="dry-run",
        id="source-1",
        sample_limit=3,
        server=None,
        profile=None,
    )

    assert handle_sources(args, client, as_json=False) == 0

    assert client.calls == [
        {
            "method": "POST",
            "path": "/api/sources/source-1/dry-run",
            "params": {"sample_limit": 3},
            "json_body": None,
            "auth_required": True,
        }
    ]
    out = capsys.readouterr().out
    assert "Collected" in out
    assert "Would Store" in out
    assert "Example" in out
