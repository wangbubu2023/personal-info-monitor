from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cli.pimctl.app import handle_auth_bundle, handle_auth_bundle_export, handle_auth_bundle_sync


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
            "site_host": "example.com",
            "cookie_count": 1,
            "storage_state_imported": True,
            "bound_sources": 2,
            "auth_config": {"id": "auth-1"},
            "browser_session": {"id": "session-1"},
        }


def test_auth_bundle_import_cli_posts_bundle_payload(tmp_path: Path, capsys):
    bundle = {
        "kind": "pim.auth_bundle",
        "version": 1,
        "site_url": "https://example.com",
        "site_host": "example.com",
        "cookies": [{"name": "session", "value": "abc", "domain": ".example.com", "path": "/"}],
    }
    bundle_path = tmp_path / "example.pim-auth-bundle.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    client = _FakeClient()
    args = SimpleNamespace(
        command="import",
        bundle_path=str(bundle_path),
        name="Imported login",
        bind_matching_sources=False,
        create_browser_session=False,
        server=None,
        profile=None,
    )

    assert handle_auth_bundle(args, client, as_json=False) == 0

    assert client.calls == [
        {
            "method": "POST",
            "path": "/api/configs/auth-bundles/import",
            "params": None,
            "json_body": {
                "bundle": bundle,
                "name": "Imported login",
                "bind_matching_sources": False,
                "create_browser_session": False,
            },
            "auth_required": True,
        }
    ]
    out = capsys.readouterr().out
    assert "example.com" in out
    assert "auth-1" in out
    assert "session-1" in out


def test_auth_bundle_export_cli_uses_local_backend_helper(monkeypatch, tmp_path: Path, capsys):
    calls = []

    async def fake_export_auth_bundle(**kwargs):
        calls.append(kwargs)
        return {
            "site_host": "example.com",
            "cookies": [{"name": "session", "value": "abc"}],
            "storage_state": {"cookies": [{"name": "session", "value": "abc"}]},
        }

    monkeypatch.setattr(
        "app.platform.auth.bundle.export_auth_bundle",
        fake_export_auth_bundle,
    )
    output_path = tmp_path / "out.pim-auth-bundle.json"
    args = SimpleNamespace(
        site_url="https://example.com",
        out=str(output_path),
        profile_dir=str(tmp_path / "profile"),
        headless=True,
        dwell_seconds=12,
        name="Example login",
        server=None,
        profile=None,
    )

    assert handle_auth_bundle_export(args, as_json=False) == 0

    assert calls == [
        {
            "site_url": "https://example.com",
            "output_path": output_path,
            "profile_dir": str(tmp_path / "profile"),
            "headless": True,
            "dwell_seconds": 12,
            "name": "Example login",
        }
    ]
    out = capsys.readouterr().out
    assert str(output_path) in out
    assert "example.com" in out
    assert "Storage State" in out


def test_auth_bundle_sync_exports_uploads_and_imports_remote(monkeypatch, tmp_path: Path, capsys):
    export_calls = []
    run_calls = []

    async def fake_export_auth_bundle(**kwargs):
        export_calls.append(kwargs)
        output_path = Path(kwargs["output_path"])
        output_path.write_text("{}", encoding="utf-8")
        return {
            "site_host": "example.com",
            "cookies": [{"name": "session", "value": "abc"}],
            "storage_state": {"cookies": [{"name": "session", "value": "abc"}]},
        }

    def fake_run(cmd, *, check):
        run_calls.append((cmd, check))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("app.platform.auth.bundle.export_auth_bundle", fake_export_auth_bundle)
    monkeypatch.setattr("cli.pimctl.app.subprocess.run", fake_run)

    output_path = tmp_path / "example.pim-auth-bundle.json"
    args = SimpleNamespace(
        site_url="https://example.com",
        remote="pim@example-vps",
        remote_pim="~/personal-info-monitor",
        remote_dir="/tmp/pim-auth-bundles",
        remote_server=None,
        remote_api_key=None,
        remote_profile=None,
        out=str(output_path),
        name="Example login",
        profile_dir=str(tmp_path / "profile"),
        headless=True,
        dwell_seconds=12,
        identity_file=str(tmp_path / "id_ed25519"),
        ssh_option=["StrictHostKeyChecking=no"],
        ssh_bin="ssh",
        scp_bin="scp",
        bind_matching_sources=True,
        create_browser_session=True,
        keep_remote=False,
        server=None,
        profile=None,
    )

    assert handle_auth_bundle_sync(args, as_json=False) == 0

    assert export_calls == [
        {
            "site_url": "https://example.com",
            "output_path": output_path,
            "profile_dir": str(tmp_path / "profile"),
            "headless": True,
            "dwell_seconds": 12,
            "name": "Example login",
        }
    ]
    assert run_calls[0] == (
        [
            "ssh",
            "-i",
            str(tmp_path / "id_ed25519"),
            "-o",
            "StrictHostKeyChecking=no",
            "pim@example-vps",
            "mkdir -p -- /tmp/pim-auth-bundles",
        ],
        True,
    )
    assert run_calls[1][0][:7] == [
        "scp",
        "-i",
        str(tmp_path / "id_ed25519"),
        "-o",
        "StrictHostKeyChecking=no",
        str(output_path),
        "pim@example-vps:/tmp/pim-auth-bundles/example.pim-auth-bundle.json",
    ]
    remote_command = run_calls[2][0][-1]
    assert "cd $HOME/personal-info-monitor" in remote_command
    assert "./pimctl auth-bundle import /tmp/pim-auth-bundles/example.pim-auth-bundle.json" in remote_command
    assert "--name 'Example login'" in remote_command
    assert "trap 'rm -f -- /tmp/pim-auth-bundles/example.pim-auth-bundle.json' EXIT" in remote_command

    out = capsys.readouterr().out
    assert "pim@example-vps" in out
    assert "Remote Deleted" in out
