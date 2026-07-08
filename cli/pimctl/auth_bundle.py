"""Auth Bundle CLI handlers."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from cli.pimctl import __version__
from cli.pimctl.client import APIClient, CLIError
from cli.pimctl.config import DEFAULT_SERVER
from cli.pimctl.output import emit_success, print_key_values


def _env_value(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _build_meta(args, *, server: str | None = None) -> dict[str, Any]:
    return {
        "server": server or getattr(args, "server", None) or _env_value("PIM_SERVER") or DEFAULT_SERVER,
        "cli_version": __version__,
        "profile": getattr(args, "profile", None),
    }


def _ensure_backend_import_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    backend_path = repo_root / "backend"
    if backend_path.exists():
        backend_text = str(backend_path)
        if backend_text not in sys.path:
            sys.path.insert(0, backend_text)


def handle_auth_bundle_export(args, *, as_json: bool) -> int:
    _ensure_backend_import_path()
    try:
        from app.platform.auth.bundle import default_bundle_output, export_auth_bundle
    except ImportError as exc:
        raise CLIError(
            "backend_unavailable",
            "Cannot import PIM backend modules. Run this command from the PIM repository checkout.",
            2,
        ) from exc

    output_path = Path(args.out).expanduser() if args.out else default_bundle_output(args.site_url)
    try:
        bundle = asyncio.run(
            export_auth_bundle(
                site_url=args.site_url,
                output_path=output_path,
                profile_dir=args.profile_dir,
                headless=bool(args.headless),
                dwell_seconds=int(args.dwell_seconds or 0),
                name=args.name,
            )
        )
    except ValueError as exc:
        raise CLIError("auth_bundle_export_failed", str(exc), 1) from exc
    except RuntimeError as exc:
        raise CLIError("auth_bundle_export_failed", str(exc), 1) from exc

    data = {
        "bundle_path": str(output_path),
        "site_host": bundle.get("site_host"),
        "cookie_count": len(bundle.get("cookies") or []),
        "has_storage_state": bool(bundle.get("storage_state")),
    }
    emit_success(
        data,
        as_json=as_json,
        meta=_build_meta(args),
        renderer=lambda d: print_key_values([
            ("Bundle", d.get("bundle_path")),
            ("Site Host", d.get("site_host")),
            ("Cookies", d.get("cookie_count")),
            ("Storage State", d.get("has_storage_state")),
        ]),
    )
    return 0


def handle_auth_bundle_sync(args, *, as_json: bool) -> int:
    output_path, export_data = _export_auth_bundle_for_args(args)
    remote_filename = output_path.name
    remote_dir = str(args.remote_dir or "/tmp/pim-auth-bundles").rstrip("/") or "/tmp/pim-auth-bundles"
    remote_path = f"{remote_dir}/{remote_filename}"

    try:
        _run_remote_auth_bundle_sync(args, output_path=output_path, remote_dir=remote_dir, remote_path=remote_path)
    except subprocess.CalledProcessError as exc:
        raise CLIError(
            "auth_bundle_sync_failed",
            f"Auth Bundle sync command failed with exit code {exc.returncode}",
            int(exc.returncode or 1),
        ) from exc
    except OSError as exc:
        raise CLIError("auth_bundle_sync_failed", str(exc), 1) from exc

    data = {
        **export_data,
        "remote": args.remote,
        "remote_path": remote_path,
        "remote_deleted": not bool(args.keep_remote),
    }
    emit_success(
        data,
        as_json=as_json,
        meta=_build_meta(args),
        renderer=lambda d: print_key_values([
            ("Bundle", d.get("bundle_path")),
            ("Site Host", d.get("site_host")),
            ("Cookies", d.get("cookie_count")),
            ("Storage State", d.get("has_storage_state")),
            ("Remote", d.get("remote")),
            ("Remote Path", d.get("remote_path")),
            ("Remote Deleted", d.get("remote_deleted")),
        ]),
    )
    return 0


def _export_auth_bundle_for_args(args) -> tuple[Path, dict[str, Any]]:
    _ensure_backend_import_path()
    try:
        from app.platform.auth.bundle import default_bundle_output, export_auth_bundle
    except ImportError as exc:
        raise CLIError(
            "backend_unavailable",
            "Cannot import PIM backend modules. Run this command from the PIM repository checkout.",
            2,
        ) from exc

    output_path = Path(args.out).expanduser() if args.out else default_bundle_output(args.site_url)
    try:
        bundle = asyncio.run(
            export_auth_bundle(
                site_url=args.site_url,
                output_path=output_path,
                profile_dir=args.profile_dir,
                headless=bool(args.headless),
                dwell_seconds=int(args.dwell_seconds or 0),
                name=args.name,
            )
        )
    except ValueError as exc:
        raise CLIError("auth_bundle_export_failed", str(exc), 1) from exc
    except RuntimeError as exc:
        raise CLIError("auth_bundle_export_failed", str(exc), 1) from exc
    return output_path, {
        "bundle_path": str(output_path),
        "site_host": bundle.get("site_host"),
        "cookie_count": len(bundle.get("cookies") or []),
        "has_storage_state": bool(bundle.get("storage_state")),
    }


def _normalize_wizard_site_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"https://{text}"
    if not (text.startswith("https://") or text.startswith("http://")):
        raise CLIError(
            "invalid_site_url",
            "Site URL must start with http:// or https://, or be a host such as example.com.",
            2,
        )
    return text


def _prompt_wizard_value(label: str, *, default: str | None = None, required: bool = True) -> str:
    if not sys.stdin.isatty():
        if default is not None:
            return default
        if required:
            raise CLIError(
                "missing_wizard_input",
                f"Missing required value for {label}. Pass it as a flag when running non-interactively.",
                2,
            )
        return ""

    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    if not value and default is not None:
        value = default
    if required and not value:
        raise CLIError("missing_wizard_input", f"{label} is required.", 2)
    return value


def _confirm_wizard(args) -> bool:
    if bool(getattr(args, "yes", False)) or not sys.stdin.isatty():
        return True
    answer = input("Continue with login-state sync? [Y/n]: ").strip().lower()
    return answer in {"", "y", "yes"}


def _resolve_auth_bundle_wizard_args(args) -> None:
    site_url = _normalize_wizard_site_url(getattr(args, "site_url", "") or "")
    if not site_url:
        site_url = _normalize_wizard_site_url(
            _prompt_wizard_value("Site URL to log in to", required=True)
        )
    args.site_url = site_url

    remote = str(getattr(args, "remote", "") or "").strip()
    if not remote:
        remote = _prompt_wizard_value("VPS SSH target (for example pim@1.2.3.4)", required=True)
    args.remote = remote

    remote_pim = str(getattr(args, "remote_pim", "") or "").strip()
    if not remote_pim:
        remote_pim = _prompt_wizard_value(
            "PIM checkout path on VPS",
            default="~/personal-info-monitor",
            required=True,
        )
    args.remote_pim = remote_pim


def _print_auth_bundle_wizard_intro(args) -> None:
    print("PIM login-state sync wizard")
    print("---------------------------")
    print("This will:")
    print("  1. open a local browser so you can log in manually")
    print("  2. capture only the target site's cookies/storage_state")
    print("  3. upload the temporary bundle to the VPS over scp")
    print("  4. import it into the remote PIM and bind matching sources")
    print()
    print_key_values([
        ("Site", args.site_url),
        ("Remote", args.remote),
        ("Remote PIM", args.remote_pim),
        ("Remote server", args.remote_server or "remote default/local profile"),
        ("Bind sources", args.bind_matching_sources),
        ("Create browser session", args.create_browser_session),
        ("Delete remote temp file", not bool(args.keep_remote)),
    ])
    print()


def handle_auth_bundle_wizard(args, *, as_json: bool) -> int:
    """Friendlier wrapper around ``auth-bundle sync`` for local -> VPS migration."""
    _resolve_auth_bundle_wizard_args(args)

    quiet = bool(getattr(args, "quiet", False))
    if not as_json and not quiet:
        _print_auth_bundle_wizard_intro(args)
    if not _confirm_wizard(args):
        if not as_json:
            print("Cancelled.")
        return 0

    rc = handle_auth_bundle_sync(args, as_json=as_json)
    if rc == 0 and not as_json and not quiet:
        print()
        print("Next checks:")
        print(f"  ssh {args.remote!s} 'cd {args.remote_pim!s} && ./pimctl sources list --json'")
        print(f"  ssh {args.remote!s} 'cd {args.remote_pim!s} && ./pimctl sources fetch-all'")
        print("If a source still reports session_expired, rerun this wizard for that site.")
    return rc


def _ssh_base_args(args) -> list[str]:
    parts: list[str] = []
    identity_file = getattr(args, "identity_file", None)
    if identity_file:
        parts.extend(["-i", str(Path(identity_file).expanduser())])
    for option in getattr(args, "ssh_option", None) or []:
        parts.extend(["-o", str(option)])
    return parts


def _remote_import_command(args, remote_path: str) -> str:
    command = [
        "./pimctl",
        "auth-bundle",
        "import",
        remote_path,
    ]
    if args.name:
        command.extend(["--name", args.name])
    if not bool(args.bind_matching_sources):
        command.append("--no-bind")
    if not bool(args.create_browser_session):
        command.append("--no-browser-session")
    if args.remote_server:
        command.extend(["--server", args.remote_server])
    if args.remote_api_key:
        command.extend(["--api-key", args.remote_api_key])
    if args.remote_profile:
        command.extend(["--profile", args.remote_profile])

    cd = f"cd {_quote_remote_path(str(args.remote_pim))}"
    import_cmd = " ".join(shlex.quote(str(part)) for part in command)
    if args.keep_remote:
        return f"{cd} && {import_cmd}"
    cleanup = f"rm -f -- {shlex.quote(remote_path)}"
    return f"{cd} && trap {shlex.quote(cleanup)} EXIT && {import_cmd}"


def _quote_remote_path(path: str) -> str:
    text = str(path or "").strip()
    if text == "~":
        return "$HOME"
    if text.startswith("~/"):
        return "$HOME/" + shlex.quote(text[2:])
    return shlex.quote(text)


def _run_remote_auth_bundle_sync(args, *, output_path: Path, remote_dir: str, remote_path: str) -> None:
    ssh_args = _ssh_base_args(args)
    mkdir_cmd = f"mkdir -p -- {shlex.quote(remote_dir)}"
    subprocess.run([args.ssh_bin, *ssh_args, args.remote, mkdir_cmd], check=True)
    subprocess.run(
        [args.scp_bin, *ssh_args, str(output_path), f"{args.remote}:{remote_path}"],
        check=True,
    )
    subprocess.run([args.ssh_bin, *ssh_args, args.remote, _remote_import_command(args, remote_path)], check=True)


def handle_auth_bundle(args, client: APIClient, *, as_json: bool) -> int:
    if args.command == "import":
        bundle_path = Path(args.bundle_path).expanduser()
        try:
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise CLIError("auth_bundle_not_found", f"Auth Bundle not found: {bundle_path}", 4) from exc
        except json.JSONDecodeError as exc:
            raise CLIError("auth_bundle_invalid", f"Auth Bundle is not valid JSON: {exc}", 2) from exc
        payload = {
            "bundle": bundle,
            "name": args.name,
            "bind_matching_sources": bool(args.bind_matching_sources),
            "create_browser_session": bool(args.create_browser_session),
        }
        data = client.request("POST", "/api/configs/auth-bundles/import", json_body=payload)
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda d: print_key_values([
                ("Site Host", d.get("site_host")),
                ("Cookies", d.get("cookie_count")),
                ("Storage State", d.get("storage_state_imported")),
                ("Bound Sources", d.get("bound_sources")),
                ("Auth Config", (d.get("auth_config") or {}).get("id")),
                ("Browser Session", (d.get("browser_session") or {}).get("id")),
            ]),
        )
        return 0

    raise CLIError("missing_command", "Missing auth-bundle subcommand", 2)
