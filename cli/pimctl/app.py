"""Main application for pimctl."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from cli.pimctl import __version__
from cli.pimctl.auth_bundle import (
    handle_auth_bundle,
    handle_auth_bundle_export,
    handle_auth_bundle_sync,
    handle_auth_bundle_wizard,
)
from cli.pimctl.client import APIClient, CLIError
from cli.pimctl.config import (
    DEFAULT_PROFILE,
    DEFAULT_SERVER,
    clear_profile_api_key,
    get_profile,
    load_config,
    read_local_runtime_key,
    upsert_profile,
)
from cli.pimctl.output import emit_error, emit_success, print_key_values, print_table


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pimctl", description="Personal Info Monitor control CLI")
    parser.add_argument("--server", help="Base server URL, e.g. http://127.0.0.1:8000")
    parser.add_argument("--api-key", help="API key for authenticated endpoints")
    parser.add_argument("--profile", default=None, help="Named CLI profile")
    parser.add_argument("--json", action="store_true", help="Emit JSON envelope output")
    parser.add_argument("--output", choices=["json", "table", "text"], help="Output format")
    parser.add_argument("--quiet", action="store_true", help="Reduce non-essential output")
    parser.add_argument("--timeout", type=int, help="Request timeout in seconds")
    parser.add_argument("--version", action="store_true", help="Show CLI version")

    subparsers = parser.add_subparsers(dest="resource")

    _build_auth_parser(subparsers)
    _build_system_parser(subparsers)
    _build_sources_parser(subparsers)
    _build_contents_parser(subparsers)
    _build_keywords_parser(subparsers)
    _build_settings_parser(subparsers)
    _build_digest_parser(subparsers)
    _build_auth_bundle_parser(subparsers)

    return parser


def _build_auth_parser(subparsers) -> None:
    parser = subparsers.add_parser("auth", help="Manage CLI authentication profiles")
    sub = parser.add_subparsers(dest="command")

    login = sub.add_parser("login", help="Save server/API key into a profile")
    login.add_argument("--set-default", action="store_true", help="Set this profile as default")

    sub.add_parser("whoami", help="Show the resolved CLI profile")
    sub.add_parser("logout", help="Remove the stored API key from the selected profile")


def _build_auth_bundle_parser(subparsers) -> None:
    parser = subparsers.add_parser("auth-bundle", help="Export/import reusable website login bundles")
    sub = parser.add_subparsers(dest="command")

    export = sub.add_parser("export", help="Open a local browser and write an Auth Bundle file")
    export.add_argument("site_url", help="Target site URL, e.g. https://www.wsj.com")
    export.add_argument("--out", help="Output .pim-auth-bundle.json path")
    export.add_argument("--name", help="Display name stored in the bundle")
    export.add_argument("--profile-dir", help="Persistent browser profile dir for the local login session")
    export.add_argument("--headless", action="store_true", help="Run without a visible browser window")
    export.add_argument("--dwell-seconds", type=int, default=300, help="Max wait time for manual login")

    import_parser = sub.add_parser("import", help="Import an Auth Bundle into a running PIM server")
    import_parser.add_argument("bundle_path", help="Path to .pim-auth-bundle.json")
    import_parser.add_argument("--name", help="Override the AuthConfig display name on the server")
    import_parser.add_argument("--no-bind", dest="bind_matching_sources", action="store_false")
    import_parser.add_argument("--no-browser-session", dest="create_browser_session", action="store_false")
    import_parser.set_defaults(bind_matching_sources=True, create_browser_session=True)

    sync = sub.add_parser("sync", help="Capture locally, upload to a VPS, and import the Auth Bundle there")
    sync.add_argument("site_url", help="Target site URL, e.g. https://www.wsj.com")
    sync.add_argument("--remote", required=True, help="SSH target, e.g. pim@your-vps")
    sync.add_argument("--remote-pim", default="~/personal-info-monitor", help="PIM checkout path on the VPS")
    sync.add_argument("--remote-dir", default="/tmp/pim-auth-bundles", help="Temporary upload directory on the VPS")
    sync.add_argument("--remote-server", help="Server URL used by remote pimctl; default is remote local server")
    sync.add_argument("--remote-api-key", help="API key used by remote pimctl; default reads remote runtime secret/profile")
    sync.add_argument("--remote-profile", help="Remote pimctl profile name")
    sync.add_argument("--out", help="Local output .pim-auth-bundle.json path")
    sync.add_argument("--name", help="Display/import name stored in the bundle")
    sync.add_argument("--profile-dir", help="Persistent browser profile dir for the local login session")
    sync.add_argument("--headless", action="store_true", help="Run without a visible browser window")
    sync.add_argument("--dwell-seconds", type=int, default=300, help="Max wait time for manual login")
    sync.add_argument("--identity-file", help="SSH identity file")
    sync.add_argument("--ssh-option", action="append", default=[], help="Extra ssh/scp -o option; may repeat")
    sync.add_argument("--ssh-bin", default="ssh", help=argparse.SUPPRESS)
    sync.add_argument("--scp-bin", default="scp", help=argparse.SUPPRESS)
    sync.add_argument("--no-bind", dest="bind_matching_sources", action="store_false")
    sync.add_argument("--no-browser-session", dest="create_browser_session", action="store_false")
    sync.add_argument("--keep-remote", action="store_true", help="Do not delete the uploaded bundle after import")
    sync.set_defaults(bind_matching_sources=True, create_browser_session=True)

    wizard = sub.add_parser(
        "wizard",
        help="Guided local-browser to VPS login-state sync",
        description=(
            "Open a local browser, capture the login state, upload it to a VPS, "
            "and import it into the remote PIM instance. Missing values are "
            "prompted interactively when stdin is a TTY."
        ),
    )
    wizard.add_argument("site_url", nargs="?", help="Target site URL, e.g. https://www.wsj.com")
    wizard.add_argument("--remote", help="SSH target, e.g. pim@your-vps")
    wizard.add_argument("--remote-pim", default="~/personal-info-monitor", help="PIM checkout path on the VPS")
    wizard.add_argument("--remote-dir", default="/tmp/pim-auth-bundles", help="Temporary upload directory on the VPS")
    wizard.add_argument("--remote-server", help="Server URL used by remote pimctl; default is remote local server")
    wizard.add_argument("--remote-api-key", help="API key used by remote pimctl; default reads remote runtime secret/profile")
    wizard.add_argument("--remote-profile", help="Remote pimctl profile name")
    wizard.add_argument("--out", help="Local output .pim-auth-bundle.json path")
    wizard.add_argument("--name", help="Display/import name stored in the bundle")
    wizard.add_argument("--profile-dir", help="Persistent browser profile dir for the local login session")
    wizard.add_argument("--headless", action="store_true", help="Run without a visible browser window")
    wizard.add_argument("--dwell-seconds", type=int, default=300, help="Max wait time for manual login")
    wizard.add_argument("--identity-file", help="SSH identity file")
    wizard.add_argument("--ssh-option", action="append", default=[], help="Extra ssh/scp -o option; may repeat")
    wizard.add_argument("--ssh-bin", default="ssh", help=argparse.SUPPRESS)
    wizard.add_argument("--scp-bin", default="scp", help=argparse.SUPPRESS)
    wizard.add_argument("--no-bind", dest="bind_matching_sources", action="store_false")
    wizard.add_argument("--no-browser-session", dest="create_browser_session", action="store_false")
    wizard.add_argument("--keep-remote", action="store_true", help="Do not delete the uploaded bundle after import")
    wizard.add_argument("--yes", action="store_true", help="Skip the final confirmation prompt")
    wizard.set_defaults(bind_matching_sources=True, create_browser_session=True)


def _build_system_parser(subparsers) -> None:
    parser = subparsers.add_parser("system", help="Inspect system status")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("health", help="Liveness probe — unauthenticated, fast (GET /livez)")
    sub.add_parser("health-check", help="Authenticated deep health check: DB + scheduler + disk (GET /health)")
    sub.add_parser("metrics", help="Show runtime metrics (request counts, latency, source stats)")
    sub.add_parser("queue", help="Show task queue and fetch worker status")
    sub.add_parser("stats", help="Show dashboard summary stats")
    sub.add_parser("search-rebuild", help="Trigger a full rebuild of the search index")
    sub.add_parser("doctor", help="Perform a full system diagnostic audit")


def _build_sources_parser(subparsers) -> None:
    parser = subparsers.add_parser("sources", help="Manage monitoring sources")
    sub = parser.add_subparsers(dest="command")

    list_parser = sub.add_parser("list", help="List sources")
    list_parser.add_argument("--type")
    list_parser.add_argument("--enabled", choices=["true", "false"])
    list_parser.add_argument("--search")
    list_parser.add_argument("--page", type=int, default=1)
    list_parser.add_argument("--page-size", type=int, default=20)

    get_parser = sub.add_parser("get", help="Get one source")
    get_parser.add_argument("id")

    add_parser = sub.add_parser("add", help="Create a source")
    add_parser.add_argument("--name", required=True)
    add_parser.add_argument("--type", required=True, choices=["website", "rss", "x", "youtube", "podcast"])
    add_parser.add_argument("--url", required=True)
    add_parser.add_argument("--extra-url", action="append", default=[])
    add_parser.add_argument("--fetch-interval", type=int, default=60)
    add_parser.add_argument("--disabled", action="store_true")
    add_parser.add_argument("--auth-required", action="store_true")
    add_parser.add_argument("--auth-config-id")

    delete_parser = sub.add_parser("delete", help="Delete a source")
    delete_parser.add_argument("id")

    probe_parser = sub.add_parser("probe", help="Probe an existing source")
    probe_parser.add_argument("id")

    probe_url_parser = sub.add_parser("probe-url", help="Probe a URL without creating a source")
    probe_url_parser.add_argument("url")
    probe_url_parser.add_argument("--type", default="website")

    dry_run_parser = sub.add_parser("dry-run", help="Run collect/normalize/build diagnostics without writing")
    dry_run_parser.add_argument("id")
    dry_run_parser.add_argument("--sample-limit", type=int, default=5)

    fetch_parser = sub.add_parser("fetch", help="Trigger a fetch for one source")
    fetch_parser.add_argument("id")

    sub.add_parser("fetch-all", help="Trigger fetch for all active sources")

    update_parser = sub.add_parser("update", help="Update an existing source")
    update_parser.add_argument("id")
    update_parser.add_argument("--name")
    update_parser.add_argument("--url")
    update_parser.add_argument("--fetch-interval", type=int)
    update_parser.add_argument("--enabled", choices=["true", "false"])

    sub.add_parser("export", help="Export all source configurations")


def _build_contents_parser(subparsers) -> None:
    parser = subparsers.add_parser("contents", help="Inspect collected contents")
    sub = parser.add_subparsers(dest="command")

    list_parser = sub.add_parser("list", help="List contents")
    list_parser.add_argument("--source-id")
    list_parser.add_argument("--source-type")
    list_parser.add_argument("--read", choices=["true", "false"])
    list_parser.add_argument("--favorited", choices=["true", "false"])
    list_parser.add_argument("--archived", choices=["true", "false"])
    list_parser.add_argument("--from-date")
    list_parser.add_argument("--to-date")
    list_parser.add_argument("--search")
    list_parser.add_argument("--page", type=int, default=1)
    list_parser.add_argument("--page-size", type=int, default=20)

    get_parser = sub.add_parser("get", help="Get one content item")
    get_parser.add_argument("id")

    search_parser = sub.add_parser("search", help="Search contents by keyword")
    search_parser.add_argument("query")
    search_parser.add_argument("--page", type=int, default=1)
    search_parser.add_argument("--page-size", type=int, default=20)
    
    sub.add_parser("export-md", help="Trigger manual markdown export")

    cleanup_parser = sub.add_parser("cleanup-low-signal", help="Dry-run or delete historical low-signal website contents")
    cleanup_parser.add_argument("--apply", action="store_true", help="Delete matched contents instead of dry-run only")
    cleanup_parser.add_argument("--source-id")
    cleanup_parser.add_argument("--preview-limit", type=int, default=20)

    sub.add_parser("delete", help="Delete a content item").add_argument("id")

    reader_parser = sub.add_parser("reader", help="Fetch full reader view of a content item")
    reader_parser.add_argument("id")
    reader_parser.add_argument("--translate", action="store_true", help="Request translated content")

    cleanup_junk_parser = sub.add_parser("cleanup-junk", help="Dry-run or delete junk contents (binary blobs, thin RSS rows)")
    cleanup_junk_parser.add_argument("--apply", action="store_true", help="Delete matched contents instead of dry-run")
    cleanup_junk_parser.add_argument("--source-id")
    cleanup_junk_parser.add_argument("--preview-limit", type=int, default=30)
    cleanup_junk_parser.add_argument("--no-binary", action="store_true", help="Skip embedded binary detection")
    cleanup_junk_parser.add_argument("--no-thin-rss", action="store_true", help="Skip thin RSS text detection")

    sub.add_parser("mark-read", help="Mark content as read").add_argument("id")
    sub.add_parser("mark-unread", help="Mark content as unread").add_argument("id")
    sub.add_parser("favorite", help="Toggle content favorite on").add_argument("id")
    sub.add_parser("unfavorite", help="Toggle content favorite off").add_argument("id")
    sub.add_parser("archive", help="Archive content").add_argument("id")
    sub.add_parser("unarchive", help="Unarchive content").add_argument("id")


def _build_settings_parser(subparsers) -> None:
    parser = subparsers.add_parser("settings", help="Inspect system settings")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("get", help="Get current settings")
    sub.add_parser("limits", help="Get runtime limits")
    
    set_parser = sub.add_parser("set", help="Set a configuration setting")
    set_parser.add_argument("--key", required=True, help="Setting key")
    set_parser.add_argument("--value", required=True, help="Setting value")


def _build_keywords_parser(subparsers) -> None:
    parser = subparsers.add_parser("keywords", help="Manage keyword monitors")
    sub = parser.add_subparsers(dest="command")

    list_parser = sub.add_parser("list", help="List all keywords")
    list_parser.add_argument("--enabled", choices=["true", "false"], help="Filter by enabled state")

    sub.add_parser("get", help="Get a keyword by ID").add_argument("id")

    add_parser = sub.add_parser("add", help="Create a keyword monitor")
    add_parser.add_argument("keyword", help="Keyword text to monitor")
    add_parser.add_argument("--match-type", default="contains",
                            choices=["contains", "exact", "regex"],
                            help="Match algorithm (default: contains)")
    add_parser.add_argument("--match-scope", default="title_content",
                            choices=["title", "content", "title_content"],
                            help="Fields to search (default: title_content)")
    add_parser.add_argument("--description")
    add_parser.add_argument("--color", default="#3b82f6", help="Highlight color (hex)")
    add_parser.add_argument("--case-sensitive", action="store_true")
    add_parser.add_argument("--notify", action="store_true", help="Send in-app notification")
    add_parser.add_argument("--notify-email", action="store_true", help="Send email notification")
    add_parser.add_argument("--disabled", action="store_true")

    batch_add_parser = sub.add_parser("batch-add", help="Create multiple keywords with shared settings")
    batch_add_parser.add_argument("keywords", nargs="+", help="Space-separated keywords to add")
    batch_add_parser.add_argument("--match-type", default="contains",
                                  choices=["contains", "exact", "regex"])
    batch_add_parser.add_argument("--match-scope", default="title_content",
                                  choices=["title", "content", "title_content"])
    batch_add_parser.add_argument("--description")
    batch_add_parser.add_argument("--color", default="#3b82f6")
    batch_add_parser.add_argument("--case-sensitive", action="store_true")
    batch_add_parser.add_argument("--notify", action="store_true")
    batch_add_parser.add_argument("--notify-email", action="store_true")
    batch_add_parser.add_argument("--disabled", action="store_true")

    update_parser = sub.add_parser("update", help="Update a keyword")
    update_parser.add_argument("id")
    update_parser.add_argument("--match-type", choices=["contains", "exact", "regex"])
    update_parser.add_argument("--match-scope", choices=["title", "content", "title_content"])
    update_parser.add_argument("--description")
    update_parser.add_argument("--color")
    update_parser.add_argument("--case-sensitive", choices=["true", "false"])
    update_parser.add_argument("--notify", choices=["true", "false"])
    update_parser.add_argument("--notify-email", choices=["true", "false"])
    update_parser.add_argument("--enabled", choices=["true", "false"])

    batch_update_parser = sub.add_parser("batch-update", help="Update shared fields across multiple keywords")
    batch_update_parser.add_argument("ids", nargs="+", help="Keyword IDs to update")
    batch_update_parser.add_argument("--enabled", choices=["true", "false"])
    batch_update_parser.add_argument("--notify", choices=["true", "false"])
    batch_update_parser.add_argument("--notify-email", choices=["true", "false"])
    batch_update_parser.add_argument("--color")
    batch_update_parser.add_argument("--match-type", choices=["contains", "exact", "regex"])
    batch_update_parser.add_argument("--match-scope", choices=["title", "content", "title_content"])

    sub.add_parser("delete", help="Delete a keyword").add_argument("id")


def _build_digest_parser(subparsers) -> None:
    parser = subparsers.add_parser("digest", help="Inspect digest data")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("latest", help="Get today's digest")
    sub.add_parser("stats", help="Get digest statistics for recent days")
    hourly_list = sub.add_parser("hourly-list", help="List available hourly digests")
    hourly_list.add_argument("--date", help="Date in YYYY-MM-DD format (default: today)")
    day = sub.add_parser("day", help="Get digest for a date")
    day.add_argument("date", help="Date in YYYY-MM-DD format")
    hour = sub.add_parser("hour", help="Get a single hourly digest by label")
    hour.add_argument("hour", help="Hour in YYYY-MM-DDTHH format")


def _build_atoms_parser(subparsers) -> None:
    parser = subparsers.add_parser("atoms", help="News atom library")
    sub = parser.add_subparsers(dest="command")

    list_parser = sub.add_parser("list", help="List atoms")
    list_parser.add_argument("--type", dest="atom_type", help="信息|观点|数据")
    list_parser.add_argument("--domain")
    list_parser.add_argument("--verified", choices=["true", "false"])
    list_parser.add_argument("--atom-source")
    list_parser.add_argument("--content-id")
    list_parser.add_argument("--search")
    list_parser.add_argument("--page", type=int, default=1)
    list_parser.add_argument("--page-size", type=int, default=20)

    sub.add_parser("stats", help="Atom library statistics")
    get_parser = sub.add_parser("get", help="Get one atom")
    get_parser.add_argument("atom_id")
    verify_parser = sub.add_parser("verify", help="Mark atom as verified")
    verify_parser.add_argument("atom_id")
    atomize_parser = sub.add_parser("atomize", help="Re-extract atoms for one content item")
    atomize_parser.add_argument("content_id")

    backfill_parser = sub.add_parser("backfill", help="Backfill atom extraction for historical contents")
    backfill_parser.add_argument("--limit", type=int, default=500)
    backfill_parser.add_argument("--since", help="ISO date, e.g. 2026-01-01")
    backfill_parser.add_argument("--content-id")
    backfill_parser.add_argument("--dry-run", action="store_true")

    backfill_status = sub.add_parser("backfill-status", help="Show backfill job progress")
    backfill_status.add_argument("job_id")

    relations = sub.add_parser("relations", help="Cross-article atom relations")
    rel_sub = relations.add_subparsers(dest="rel_command")

    rel_list = rel_sub.add_parser("list", help="List atom relations")
    rel_list.add_argument("--atom-id")
    rel_list.add_argument("--verified", choices=["true", "false"])
    rel_list.add_argument("--page", type=int, default=1)
    rel_list.add_argument("--page-size", type=int, default=20)

    rel_reconcile = rel_sub.add_parser("reconcile", help="Re-run relation inference (async job)")
    rel_reconcile.add_argument("--limit", type=int, default=1000)
    rel_reconcile.add_argument("--since", help="ISO date, e.g. 2026-01-01")
    rel_reconcile.add_argument("--atom-id")
    rel_reconcile.add_argument("--dry-run", action="store_true")

    rel_reconcile_status = rel_sub.add_parser(
        "reconcile-status", help="Show relations reconcile job progress"
    )
    rel_reconcile_status.add_argument("job_id")

    rel_verify = rel_sub.add_parser("verify", help="Verify corroboration relation (+ confidence boost)")
    rel_verify.add_argument("rel_id")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    normalized_argv = _normalize_global_args(argv or sys.argv[1:])
    args = parser.parse_args(normalized_argv)

    if args.version:
        print(__version__)
        return 0

    if not args.resource:
        parser.print_help()
        return 2

    as_json = bool(args.json or args.output == "json")
    try:
        return dispatch(args, as_json=as_json)
    except CLIError as exc:
        emit_error(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            meta=_build_meta(args),
            as_json=as_json,
        )
        return exc.exit_code


def dispatch(args, *, as_json: bool) -> int:
    if args.resource == "auth-bundle" and args.command == "export":
        return handle_auth_bundle_export(args, as_json=as_json)
    if args.resource == "auth-bundle" and args.command == "sync":
        return handle_auth_bundle_sync(args, as_json=as_json)
    if args.resource == "auth-bundle" and args.command == "wizard":
        return handle_auth_bundle_wizard(args, as_json=as_json)
    if args.resource == "auth":
        return handle_auth(args, as_json=as_json)

    profile = _resolve_profile(args)
    client = APIClient(
        server=profile["server"],
        api_key=profile["api_key"],
        timeout=profile["timeout"],
    )

    if args.resource == "system":
        return handle_system(args, client, as_json=as_json)
    if args.resource == "sources":
        return handle_sources(args, client, as_json=as_json)
    if args.resource == "contents":
        return handle_contents(args, client, as_json=as_json)
    if args.resource == "keywords":
        return handle_keywords(args, client, as_json=as_json)
    if args.resource == "settings":
        return handle_settings(args, client, as_json=as_json)
    if args.resource == "digest":
        return handle_digest(args, client, as_json=as_json)
    if args.resource == "auth-bundle":
        return handle_auth_bundle(args, client, as_json=as_json)

    raise CLIError("unsupported_command", "Unsupported command", 2)


def handle_auth(args, *, as_json: bool) -> int:
    config = load_config()
    profile_name = args.profile or str(config.get("default_profile") or DEFAULT_PROFILE)

    if args.command == "login":
        server = args.server or _env_or_profile_server(config, profile_name)
        api_key = args.api_key or _env_or_profile_api_key(config, profile_name)
        if not api_key:
            raise CLIError(
                "missing_api_key",
                "API key not found. Is PIM running? Expected key at ~/.pim/data/runtime-secrets.json",
                2,
            )

        client = APIClient(server=server, api_key=api_key, timeout=args.timeout or 30)
        client.request("GET", "/api/system/queue")
        saved = upsert_profile(
            profile_name,
            server=server,
            api_key=api_key,
            output=args.output,
            timeout=args.timeout,
            make_default=bool(args.set_default),
        )
        emit_success(
            {
                "profile": saved.name,
                "server": saved.server,
                "has_api_key": True,
                "default_profile": load_config().get("default_profile"),
            },
            as_json=as_json,
            meta=_build_meta(args, server=saved.server),
            renderer=lambda data: print_key_values([
                ("Profile", data["profile"]),
                ("Server", data["server"]),
                ("Has API Key", data["has_api_key"]),
                ("Default", data["default_profile"]),
            ]),
        )
        return 0

    if args.command == "logout":
        saved = clear_profile_api_key(profile_name)
        emit_success(
            {
                "profile": saved.name,
                "server": saved.server,
                "has_api_key": False,
            },
            as_json=as_json,
            meta=_build_meta(args, server=saved.server),
            renderer=lambda data: print_key_values([
                ("Profile", data["profile"]),
                ("Server", data["server"]),
                ("Has API Key", data["has_api_key"]),
            ]),
        )
        return 0

    if args.command == "whoami":
        profile = get_profile(config, profile_name)
        server = args.server or profile.server
        api_key = args.api_key or profile.api_key
        emit_success(
            {
                "profile": profile.name,
                "server": server,
                "has_api_key": bool(api_key),
                "default_profile": config.get("default_profile"),
            },
            as_json=as_json,
            meta=_build_meta(args, server=server),
            renderer=lambda data: print_key_values([
                ("Profile", data["profile"]),
                ("Server", data["server"]),
                ("Has API Key", data["has_api_key"]),
                ("Default", data["default_profile"]),
            ]),
        )
        return 0

    raise CLIError("missing_command", "Missing auth subcommand", 2)


def _ensure_backend_import_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    backend_path = repo_root / "backend"
    if backend_path.exists():
        backend_text = str(backend_path)
        if backend_text not in sys.path:
            sys.path.insert(0, backend_text)


def handle_system(args, client: APIClient, *, as_json: bool) -> int:
    if args.command == "health":
        data = client.request("GET", "/livez", auth_required=False)
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda data: print_key_values([("Status", data.get("status"))]),
        )
        return 0

    if args.command == "health-check":
        data = client.request("GET", "/health")
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda data: (
                print_key_values([("Status", data.get("status"))]),
                print_key_values(
                    [(f"  {k}", v) for k, v in (data.get("checks") or {}).items()]
                ),
            ),
        )
        return 0

    if args.command == "metrics":
        data = client.request("GET", "/api/system/metrics")
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda data: (
                print_key_values([
                    ("Total Requests", (data.get("http") or {}).get("total_requests")),
                    ("Avg Latency ms", (data.get("http") or {}).get("avg_latency_ms")),
                    ("Max Latency ms", (data.get("http") or {}).get("max_latency_ms")),
                    ("Scheduler Running", (data.get("scheduler") or {}).get("running")),
                    ("Scheduler Jobs", (data.get("scheduler") or {}).get("job_count")),
                    ("Source Count", len(data.get("sources") or {})),
                ]),
            ),
        )
        return 0

    if args.command == "queue":
        data = client.request("GET", "/api/system/queue")
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda data: print_key_values([
                ("Running Fetches", data.get("running_fetches")),
                ("Running Processes", data.get("running_processes")),
                ("Fetch Concurrency", data.get("fetch_concurrency")),
                ("Sources Status Count", len(data.get("sources_status") or [])),
            ]),
        )
        return 0

    if args.command == "stats":
        data = client.request("GET", "/api/dashboard/stats")
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda data: print_key_values([
                ("Today Total", data.get("today_total")),
                ("Unread Count", data.get("unread_count")),
                ("Active Sources", data.get("active_sources")),
                ("Favorited Count", data.get("favorited_count")),
            ]),
        )
        return 0

    if args.command == "search-rebuild":
        data = client.request("POST", "/api/system/search/rebuild")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "doctor":
        data = client.request("GET", "/api/system/doctor")
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=_render_doctor_report,
        )
        return 0

    raise CLIError("missing_command", "Missing system subcommand", 2)


def handle_sources(args, client: APIClient, *, as_json: bool) -> int:
    if args.command == "list":
        params = {
            "page": args.page,
            "page_size": args.page_size,
            "type": args.type,
            "enabled": _optional_bool(args.enabled),
            "search": args.search,
        }
        data = client.request("GET", "/api/sources", params=params)
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda data: print_table(
                data.get("items") or [],
                [
                    ("ID", "id"),
                    ("TYPE", "type"),
                    ("NAME", "name"),
                    ("STATUS", "fetch_status"),
                    ("STRATEGY", "fetch_strategy"),
                    ("ENABLED", "enabled"),
                ],
            ),
        )
        return 0

    if args.command == "get":
        data = client.request("GET", f"/api/sources/{args.id}")
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda d: print_key_values(
                [(k, v) for k, v in d.items() if k not in ["metadata", "stats"]]
            ),
        )
        return 0

    if args.command == "add":
        payload = {
            "name": args.name,
            "type": args.type,
            "url": args.url,
            "extra_urls": args.extra_url,
            "fetch_interval": args.fetch_interval,
            "enabled": not args.disabled,
            "auth_required": args.auth_required,
            "auth_config_id": args.auth_config_id,
            "metadata": {},
        }
        data = client.request("POST", "/api/sources", json_body=payload)
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "delete":
        data = client.request("DELETE", f"/api/sources/{args.id}")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "probe":
        data = client.request("POST", f"/api/sources/{args.id}/probe")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "probe-url":
        data = client.request(
            "POST",
            "/api/sources/probe",
            json_body={"url": args.url, "type": args.type},
        )
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "dry-run":
        data = client.request(
            "POST",
            f"/api/sources/{args.id}/dry-run",
            params={"sample_limit": args.sample_limit},
        )
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=_render_source_dry_run,
        )
        return 0

    if args.command == "fetch":
        data = client.request("POST", f"/api/sources/{args.id}/fetch")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "fetch-all":
        data = client.request("POST", "/api/sources/fetch-all")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "update":
        payload = {}
        if args.name is not None:
            payload["name"] = args.name
        if args.url is not None:
            payload["url"] = args.url
        if args.fetch_interval is not None:
            payload["fetch_interval"] = args.fetch_interval
        if args.enabled is not None:
            payload["enabled"] = _optional_bool(args.enabled)
        data = client.request("PATCH", f"/api/sources/{args.id}", json_body=payload)
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "export":
        data = client.request("GET", "/api/sources/export")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    raise CLIError("missing_command", "Missing sources subcommand", 2)


def handle_contents(args, client: APIClient, *, as_json: bool) -> int:
    if args.command == "list":
        params = {
            "source_id": args.source_id,
            "source_type": args.source_type,
            "read_status": _optional_bool(args.read),
            "favorited": _optional_bool(args.favorited),
            "archived": _optional_bool(args.archived),
            "date_from": args.from_date,
            "date_to": args.to_date,
            "search": args.search,
            "page": args.page,
            "page_size": args.page_size,
        }
        data = client.request("GET", "/api/contents", params=params)
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda data: print_table(
                data.get("items") or [],
                [
                    ("ID", "id"),
                    ("TYPE", "content_type"),
                    ("SOURCE", "source_name"),
                    ("TITLE", "title"),
                    ("READ", "read_status"),
                    ("FAV", "favorited"),
                ],
            ),
        )
        return 0

    if args.command == "get":
        data = client.request("GET", f"/api/contents/{args.id}")
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda d: print_key_values(
                [(k, v) for k, v in d.items() if k not in ["full_content", "summary", "source"]]
            ),
        )
        return 0

    if args.command == "search":
        data = client.request(
            "GET",
            "/api/contents",
            params={
                "search": args.query,
                "page": args.page,
                "page_size": args.page_size,
            },
        )
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda data: print_table(
                data.get("items") or [],
                [
                    ("ID", "id"),
                    ("SOURCE", "source_name"),
                    ("TITLE", "title"),
                    ("URL", "original_url"),
                ],
            ),
        )
        return 0

    if args.command == "delete":
        data = client.request("DELETE", f"/api/contents/{args.id}")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "reader":
        params = {}
        if args.translate:
            params["translate"] = True
        data = client.request("GET", f"/api/contents/{args.id}/reader", params=params or None)
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda d: print_key_values([
                ("ID", d.get("id")),
                ("Title", d.get("title")),
                ("Translated Title", d.get("translated_title")),
                ("URL", d.get("original_url")),
                ("Extracted", bool(d.get("full_content"))),
                ("Translated", bool(d.get("translated_summary"))),
            ]),
        )
        return 0

    if args.command == "cleanup-junk":
        params = {
            "apply": args.apply,
            "source_id": args.source_id,
            "preview_limit": args.preview_limit,
            "match_embedded_binary": not args.no_binary,
            "match_rss_thin_text": not args.no_thin_rss,
        }
        data = client.request("POST", "/api/contents/cleanup-junk", params=params)
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=_render_cleanup_report,
        )
        return 0

    if args.command == "cleanup-low-signal":
        data = client.request(
            "POST",
            "/api/contents/cleanup-low-signal",
            params={
                "apply": args.apply,
                "source_id": args.source_id,
                "preview_limit": args.preview_limit,
            },
        )
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=_render_cleanup_report,
        )
        return 0

    if args.command == "export-md":
        data = client.request("POST", "/api/contents/export-md")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "mark-read":
        data = client.request("POST", f"/api/contents/{args.id}/read")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "mark-unread":
        data = client.request("PATCH", f"/api/contents/{args.id}", json_body={"read_status": False})
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "favorite":
        data = client.request("PATCH", f"/api/contents/{args.id}/favorite", json_body={"favorited": True})
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "unfavorite":
        data = client.request("PATCH", f"/api/contents/{args.id}", json_body={"favorited": False})
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "archive":
        data = client.request("PATCH", f"/api/contents/{args.id}", json_body={"archived": True})
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "unarchive":
        data = client.request("PATCH", f"/api/contents/{args.id}", json_body={"archived": False})
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    raise CLIError("missing_command", "Missing contents subcommand", 2)


def handle_keywords(args, client: APIClient, *, as_json: bool) -> int:
    if args.command == "list":
        params = {}
        enabled = _optional_bool(getattr(args, "enabled", None))
        if enabled is not None:
            params["enabled"] = enabled
        data = client.request("GET", "/api/keywords", params=params or None)
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda data: print_table(
                data.get("items") or [],
                [
                    ("ID", "id"),
                    ("KEYWORD", "keyword"),
                    ("TYPE", "match_type"),
                    ("SCOPE", "match_scope"),
                    ("ENABLED", "enabled"),
                    ("NOTIFY", "notify"),
                ],
            ),
        )
        return 0

    if args.command == "get":
        data = client.request("GET", f"/api/keywords/{args.id}")
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda d: print_key_values([
                ("ID", d.get("id")),
                ("Keyword", d.get("keyword")),
                ("Match Type", d.get("match_type")),
                ("Match Scope", d.get("match_scope")),
                ("Case Sensitive", d.get("case_sensitive")),
                ("Enabled", d.get("enabled")),
                ("Notify", d.get("notify")),
                ("Notify Email", d.get("notify_email")),
                ("Color", d.get("color")),
                ("Description", d.get("description")),
            ]),
        )
        return 0

    if args.command == "add":
        payload = {
            "keyword": args.keyword,
            "match_type": args.match_type,
            "match_scope": args.match_scope,
            "case_sensitive": args.case_sensitive,
            "notify": args.notify,
            "notify_email": args.notify_email,
            "color": args.color,
            "enabled": not args.disabled,
        }
        if args.description:
            payload["description"] = args.description
        data = client.request("POST", "/api/keywords", json_body=payload)
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "batch-add":
        payload = {
            "keywords": args.keywords,
            "match_type": args.match_type,
            "match_scope": args.match_scope,
            "case_sensitive": args.case_sensitive,
            "notify": args.notify,
            "notify_email": args.notify_email,
            "color": args.color,
            "enabled": not args.disabled,
        }
        if args.description:
            payload["description"] = args.description
        data = client.request("POST", "/api/keywords/batch", json_body=payload)
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda d: print_key_values([
                ("Created", d.get("total")),
                ("Skipped (duplicates)", len(d.get("skipped_keywords") or [])),
            ]),
        )
        return 0

    if args.command == "update":
        payload: dict = {}
        if args.match_type is not None:
            payload["match_type"] = args.match_type
        if args.match_scope is not None:
            payload["match_scope"] = args.match_scope
        if args.description is not None:
            payload["description"] = args.description
        if args.color is not None:
            payload["color"] = args.color
        if args.case_sensitive is not None:
            payload["case_sensitive"] = _optional_bool(args.case_sensitive)
        if args.notify is not None:
            payload["notify"] = _optional_bool(args.notify)
        if args.notify_email is not None:
            payload["notify_email"] = _optional_bool(args.notify_email)
        if args.enabled is not None:
            payload["enabled"] = _optional_bool(args.enabled)
        data = client.request("PATCH", f"/api/keywords/{args.id}", json_body=payload)
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "batch-update":
        payload = {"keyword_ids": args.ids}
        if args.enabled is not None:
            payload["enabled"] = _optional_bool(args.enabled)
        if args.notify is not None:
            payload["notify"] = _optional_bool(args.notify)
        if args.notify_email is not None:
            payload["notify_email"] = _optional_bool(args.notify_email)
        if args.color is not None:
            payload["color"] = args.color
        if args.match_type is not None:
            payload["match_type"] = args.match_type
        if args.match_scope is not None:
            payload["match_scope"] = args.match_scope
        data = client.request("PATCH", "/api/keywords/batch", json_body=payload)
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda d: print_key_values([("Updated", d.get("total"))]),
        )
        return 0

    if args.command == "delete":
        data = client.request("DELETE", f"/api/keywords/{args.id}")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    raise CLIError("missing_command", "Missing keywords subcommand", 2)


def handle_settings(args, client: APIClient, *, as_json: bool) -> int:
    if args.command == "get":
        data = client.request("GET", "/api/configs/settings")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0
    if args.command == "limits":
        data = client.request("GET", "/api/configs/settings")
        limits = (data or {}).get("limits") or {}
        payload = {
            "max_sources": limits.get("max_sources"),
            "max_digest_candidates": limits.get("max_digest_candidates"),
            "max_hourly_digest_input_items": limits.get("max_hourly_digest_input_items"),
        }
        emit_success(
            payload,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda d: print_key_values([
                ("Max Sources", d.get("max_sources")),
                ("Max Digest Candidates", d.get("max_digest_candidates")),
                ("Max Hourly Digest Input Items", d.get("max_hourly_digest_input_items")),
            ]),
        )
        return 0

    if args.command == "set":
        val = args.value
        if val.lower() == "true": val = True
        elif val.lower() == "false": val = False
        elif val.isdigit(): val = int(val)
        data = client.request("PATCH", "/api/configs/settings", json_body={args.key: val})
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    raise CLIError("missing_command", "Missing settings subcommand", 2)


def handle_digest(args, client: APIClient, *, as_json: bool) -> int:
    if args.command == "latest":
        data = client.request("GET", "/api/digest")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "stats":
        data = client.request("GET", "/api/digest/stats")
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda d: (
                print_key_values([
                    ("Period", f"{(d.get('period') or {}).get('start')} → {(d.get('period') or {}).get('end')}"),
                    ("Unread", d.get("unread_count")),
                    ("Favorited", d.get("favorited_count")),
                ]),
                print_table(
                    d.get("daily_counts") or [],
                    [("DATE", "date"), ("COUNT", "count")],
                ),
            ),
        )
        return 0

    if args.command == "hourly-list":
        params = {}
        if getattr(args, "date", None):
            params["date"] = args.date
        data = client.request("GET", "/api/digest/hourly", params=params or None)
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda items: print_table(
                items if isinstance(items, list) else [],
                [("HOUR", "hour"), ("COUNT", "item_count"), ("GENERATED", "generated_at")],
            ),
        )
        return 0

    if args.command == "day":
        data = client.request("GET", "/api/digest", params={"date": args.date})
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "hour":
        data = client.request("GET", f"/api/digest/hourly/{args.hour}")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    raise CLIError("missing_command", "Missing digest subcommand", 2)


def handle_atoms(args, client: APIClient, *, as_json: bool) -> int:
    if args.command == "list":
        params: dict[str, Any] = {
            "page": args.page,
            "page_size": args.page_size,
        }
        if args.atom_type:
            params["type"] = args.atom_type
        if args.domain:
            params["domain"] = args.domain
        if args.verified is not None:
            params["verified"] = _optional_bool(args.verified)
        if args.atom_source:
            params["atom_source"] = args.atom_source
        if args.content_id:
            params["content_id"] = args.content_id
        if args.search:
            params["search"] = args.search
        data = client.request("GET", "/api/atoms", params=params)
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda d: print_table(
                d.get("items") or [],
                [
                    ("ATOM_ID", "atom_id"),
                    ("TYPE", "atom_type"),
                    ("DOMAIN", "domain"),
                    ("SOURCE", "atom_source"),
                    ("VERIFIED", "verified"),
                ],
            ),
        )
        return 0

    if args.command == "stats":
        data = client.request("GET", "/api/atoms/stats")
        emit_success(
            data,
            as_json=as_json,
            meta=_build_meta(args, server=client.server),
            renderer=lambda d: print_key_values([
                ("Total", d.get("total")),
                ("Verified", d.get("verified_count")),
                ("Unverified", d.get("unverified_count")),
                ("By Type", d.get("by_type")),
            ]),
        )
        return 0

    if args.command == "get":
        data = client.request("GET", f"/api/atoms/{args.atom_id}")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "verify":
        data = client.request("POST", f"/api/atoms/{args.atom_id}/verify")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "atomize":
        data = client.request("POST", f"/api/atoms/content/{args.content_id}/atomize")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "backfill":
        payload = {"limit": args.limit, "dry_run": bool(args.dry_run)}
        if args.since:
            payload["since"] = args.since
        if args.content_id:
            payload["content_id"] = args.content_id
        data = client.request("POST", "/api/atoms/backfill", json_body=payload)
        job_id = data.get("job_id")
        if as_json or args.quiet:
            emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
            return 0
        print(f"Backfill job started: {job_id}")
        import time

        while True:
            status = client.request("GET", f"/api/atoms/backfill/{job_id}")
            print(
                f"  status={status.get('status')} processed={status.get('processed')}/{status.get('total')}",
                flush=True,
            )
            if status.get("status") in {"done", "failed"}:
                emit_success(status, as_json=False, meta=_build_meta(args, server=client.server))
                return 0 if status.get("status") == "done" else 1
            time.sleep(2)

    if args.command == "backfill-status":
        data = client.request("GET", f"/api/atoms/backfill/{args.job_id}")
        emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
        return 0

    if args.command == "relations":
        rel_cmd = getattr(args, "rel_command", None)
        if rel_cmd == "list":
            params: dict[str, Any] = {"page": args.page, "page_size": args.page_size}
            if args.atom_id:
                params["atom_id"] = args.atom_id
            if args.verified is not None:
                params["verified"] = _optional_bool(args.verified)
            data = client.request("GET", "/api/atoms/relations", params=params)
            emit_success(
                data,
                as_json=as_json,
                meta=_build_meta(args, server=client.server),
                renderer=lambda d: print_table(
                    d.get("items") or [],
                    [
                        ("REL_ID", "rel_id"),
                        ("TYPE", "relation_type"),
                        ("A", "atom_a"),
                        ("B", "atom_b"),
                        ("VERIFIED", "verified"),
                    ],
                ),
            )
            return 0

        if rel_cmd == "reconcile":
            payload = {"limit": args.limit, "dry_run": bool(args.dry_run)}
            if args.since:
                payload["since"] = args.since
            if args.atom_id:
                payload["atom_id"] = args.atom_id
            data = client.request("POST", "/api/atoms/relations/reconcile", json_body=payload)
            job_id = data.get("job_id")
            if as_json or args.quiet:
                emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
                return 0
            print(f"Relations reconcile job started: {job_id}")
            import time

            while True:
                status = client.request("GET", f"/api/atoms/relations/reconcile/{job_id}")
                print(
                    f"  status={status.get('status')} processed={status.get('processed')}/{status.get('total')} "
                    f"relations_created={status.get('relations_created', 0)}",
                    flush=True,
                )
                if status.get("status") in {"done", "failed"}:
                    emit_success(status, as_json=False, meta=_build_meta(args, server=client.server))
                    return 0 if status.get("status") == "done" else 1
                time.sleep(2)

        if rel_cmd == "reconcile-status":
            data = client.request("GET", f"/api/atoms/relations/reconcile/{args.job_id}")
            emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
            return 0

        if rel_cmd == "verify":
            data = client.request("POST", f"/api/atom-relations/{args.rel_id}/verify")
            emit_success(data, as_json=as_json, meta=_build_meta(args, server=client.server))
            return 0

        raise CLIError("missing_command", "Missing atoms relations subcommand", 2)

    raise CLIError("missing_command", "Missing atoms subcommand", 2)


def _resolve_profile(args) -> dict[str, Any]:
    config = load_config()
    profile = get_profile(config, args.profile)
    server = args.server or _env_or_profile_server(config, profile.name)
    api_key = args.api_key or _env_or_profile_api_key(config, profile.name)
    timeout = args.timeout or _env_int("PIM_TIMEOUT") or profile.timeout or 30
    return {
        "profile": profile.name,
        "server": server,
        "api_key": api_key,
        "timeout": timeout,
    }


def _env_or_profile_server(config: dict[str, Any], profile_name: str) -> str:
    return (
        _env_value("PIM_SERVER")
        or get_profile(config, profile_name).server
        or DEFAULT_SERVER
    )


def _env_or_profile_api_key(config: dict[str, Any], profile_name: str) -> str | None:
    return (
        _env_value("PIM_API_KEY")
        or get_profile(config, profile_name).api_key
        or read_local_runtime_key()
    )


def _env_value(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _env_int(name: str) -> int | None:
    value = _env_value(name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _build_meta(args, *, server: str | None = None) -> dict[str, Any]:
    return {
        "server": server or getattr(args, "server", None) or _env_value("PIM_SERVER") or DEFAULT_SERVER,
        "cli_version": __version__,
        "profile": getattr(args, "profile", None),
    }


def _optional_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.lower() == "true"


def _render_cleanup_report(data: dict[str, Any]) -> None:
    print_key_values(
        [
            ("Mode", data.get("mode")),
            ("Scanned", data.get("scanned_count")),
            ("Matched", data.get("matched_count")),
            ("Deleted", data.get("deleted_count")),
            ("By Reason", data.get("by_reason")),
            ("By Source", data.get("by_source")),
        ]
    )
    preview = data.get("preview") or []
    if preview:
        print()
        print_table(
            preview,
            [
                ("ID", "id"),
                ("REASON", "reason"),
                ("SOURCE", "source_name"),
                ("TITLE", "title"),
                ("URL", "url"),
            ],
        )


def _render_source_dry_run(data: dict[str, Any]) -> None:
    stages = data.get("stages") or {}
    collector = stages.get("collector") or {}
    normalizer = stages.get("normalizer") or {}
    builder = stages.get("builder") or {}
    warnings = data.get("warnings") or {}
    print_key_values(
        [
            ("Source", data.get("source_name")),
            ("Type", data.get("source_type")),
            ("Dry Run", data.get("dry_run")),
            ("Would Write", data.get("would_write")),
            ("Collected", collector.get("count")),
            ("Valid", normalizer.get("valid_count")),
            ("Stale Skipped", normalizer.get("stale_skipped")),
            ("Other Skipped", normalizer.get("other_skipped")),
            ("Would Store", builder.get("would_store_count")),
            ("Build Failed", builder.get("build_failed")),
            ("Warning", warnings.get("merged")),
        ]
    )
    samples = (data.get("samples") or {}).get("would_store") or []
    if samples:
        print()
        print_table(
            samples,
            [
                ("TITLE", "title"),
                ("URL", "url"),
                ("EXT_ID", "external_id"),
                ("CHARS", "full_content_chars"),
            ],
        )


def _render_doctor_report(data: dict[str, Any]) -> None:
    print("\n🩺 PIM System Diagnostic Report")
    print("=" * 40)
    
    overall = data.get("overall_status", "unknown").upper()
    status_icon = "✅" if overall == "OK" else "⚠️" if overall == "DEGRADED" else "❌"
    print(f"Overall Status: {status_icon} {overall}")
    print(f"Timestamp:      {data.get('timestamp')}")
    print("-" * 40)

    categories = [
        ("Database", "database", "🗄️"),
        ("Environment", "environment", "🌍"),
        ("Workers", "workers", "👷"),
        ("Collectors", "collectors", "🕷️"),
        ("Integrations", "integrations", "🔌"),
    ]

    for label, key, icon in categories:
        cat_data = data.get(key)
        if not cat_data:
            continue
        
        status = cat_data.get("status", "unknown")
        c_icon = "✅" if status == "ok" else "⚠️" if status == "warning" else "❌"
        print(f"\n{icon} {label}: {c_icon} {status.upper()}")
        
        for k, v in cat_data.items():
            if k in ["status", "message"]:
                continue
            print(f"  - {k.replace('_', ' ').title()}: {v}")
            
        if cat_data.get("message"):
            print(f"  ! {cat_data['message']}")

    print("\n" + "=" * 40)
    if overall != "OK":
        print("💡 Suggestion: Check logs or run 'pimctl system doctor' again after fixing reported issues.")
    print()


def _normalize_global_args(argv: list[str]) -> list[str]:
    flags_without_values = {"--json", "--quiet", "--version"}
    flags_with_values = {"--server", "--api-key", "--profile", "--output", "--timeout"}
    extracted: list[str] = []
    remaining: list[str] = []
    idx = 0

    while idx < len(argv):
        token = argv[idx]
        if token in flags_without_values:
            extracted.append(token)
            idx += 1
            continue
        if token in flags_with_values:
            extracted.append(token)
            if idx + 1 >= len(argv):
                return argv
            extracted.append(argv[idx + 1])
            idx += 2
            continue
        remaining.append(token)
        idx += 1

    return extracted + remaining


if __name__ == "__main__":
    raise SystemExit(main())
