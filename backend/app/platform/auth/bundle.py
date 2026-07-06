"""Auth Bundle import/export helpers.

An Auth Bundle is a small JSON package produced on a trusted local machine
after the user logs in with a real browser. A server-side PIM instance can
import the package into its existing AuthConfig cookie path.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from app.features import PlaywrightDisabledError, playwright_enabled
from app.platform.browser.playwright_runtime import (
    async_playwright,
    backend_name,
    default_channel,
    is_patchright_active,
    recommended_launch_args,
    timeout_error_types,
)
from app.platform.browser.playwright_stealth import stealth_init_script
from app.platform.browser.profiles import profiles_root, slugify_profile_name
from app.utils.datetime import utcnow_naive
from app.utils.url import host_matches, normalize_host

BUNDLE_KIND = "pim.auth_bundle"
BUNDLE_VERSION = 1

_BUNDLE_TOOL = "pim-auth-bundle"
_HEADFUL_LINUX_DISPLAY_ERROR = (
    "可视化浏览器无法启动：当前 Linux/VPS 环境没有 DISPLAY/WAYLAND_DISPLAY。"
    "请在本地桌面环境运行导出，或为当前 shell 配置可视化显示环境。"
)
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class AuthBundleError(ValueError):
    """Raised when an Auth Bundle is malformed or unusable."""


def default_bundle_output(site_url: str) -> Path:
    site_host = normalize_host(site_url)
    suffix = utcnow_naive().strftime("%Y%m%d%H%M%S")
    name = f"{slugify_profile_name(site_host or 'site')}-{suffix}.pim-auth-bundle.json"
    return Path.cwd() / name


def load_auth_bundle(path: str | Path) -> dict[str, Any]:
    bundle_path = Path(path).expanduser()
    try:
        payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AuthBundleError(f"Auth Bundle not found: {bundle_path}") from exc
    except json.JSONDecodeError as exc:
        raise AuthBundleError(f"Auth Bundle is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise AuthBundleError("Auth Bundle must be a JSON object")
    return payload


def write_auth_bundle(path: str | Path, bundle: dict[str, Any]) -> Path:
    bundle_path = Path(path).expanduser()
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    with contextlib.suppress(OSError):
        bundle_path.chmod(0o600)
    return bundle_path


def validate_auth_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        raise AuthBundleError("Auth Bundle must be a JSON object")
    if bundle.get("kind") != BUNDLE_KIND:
        raise AuthBundleError(f"Unsupported Auth Bundle kind: {bundle.get('kind')!r}")
    if bundle.get("version") != BUNDLE_VERSION:
        raise AuthBundleError(f"Unsupported Auth Bundle version: {bundle.get('version')!r}")

    site_url = str(bundle.get("site_url") or "").strip()
    site_host = normalize_host(bundle.get("site_host") or site_url)
    if not site_url or not site_host:
        raise AuthBundleError("Auth Bundle requires site_url and a resolvable site_host")

    cookies = bundle_cookie_items(bundle)
    if not cookies:
        raise AuthBundleError("Auth Bundle contains no usable cookies for the target site")

    normalized = dict(bundle)
    normalized["site_url"] = site_url
    normalized["site_host"] = site_host
    normalized["cookies"] = cookies
    storage_state = normalized.get("storage_state")
    if storage_state is not None and not isinstance(storage_state, dict):
        raise AuthBundleError("Auth Bundle storage_state must be an object when present")
    return normalized


def bundle_cookie_items(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    site_host = normalize_host(bundle.get("site_host") or bundle.get("site_url"))
    raw_items = bundle.get("cookies")
    if raw_items is None:
        storage_state = bundle.get("storage_state") if isinstance(bundle.get("storage_state"), dict) else {}
        raw_items = storage_state.get("cookies") if isinstance(storage_state, dict) else []
    if isinstance(raw_items, dict):
        raw_items = [{"name": k, "value": v, "domain": site_host, "path": "/"} for k, v in raw_items.items()]
    if not isinstance(raw_items, list):
        return []
    return _filter_cookie_items(raw_items, site_host)


def bundle_cookie_dict(bundle: dict[str, Any]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for item in bundle_cookie_items(bundle):
        name = str(item.get("name") or "").strip()
        value = item.get("value")
        if name and value is not None:
            cleaned[name] = str(value)
    return cleaned


def filtered_storage_state(storage_state: dict[str, Any] | None, site_host: str) -> dict[str, Any] | None:
    if not isinstance(storage_state, dict):
        return None
    cookies = _filter_cookie_items(storage_state.get("cookies") or [], site_host)
    origins: list[dict[str, Any]] = []
    for origin in storage_state.get("origins") or []:
        if not isinstance(origin, dict):
            continue
        origin_host = normalize_host(origin.get("origin"))
        if origin_host and host_matches(origin_host, site_host):
            origins.append(origin)
    return {"cookies": cookies, "origins": origins}


def build_auth_bundle(
    *,
    site_url: str,
    cookies: list[dict[str, Any]],
    storage_state: dict[str, Any] | None,
    final_url: str | None = None,
    title: str | None = None,
    profile_dir: str | None = None,
    headless: bool = False,
    dwell_seconds: int = 0,
    name: str | None = None,
) -> dict[str, Any]:
    site_host = normalize_host(site_url)
    if not site_host:
        raise AuthBundleError("Invalid site_url; cannot resolve host")
    cookie_items = _filter_cookie_items(cookies, site_host)
    if not cookie_items:
        raise AuthBundleError("No target-site cookies were captured")
    return {
        "kind": BUNDLE_KIND,
        "version": BUNDLE_VERSION,
        "name": name or f"{site_host} Auth Bundle",
        "site_url": site_url,
        "site_host": site_host,
        "created_at": utcnow_naive().isoformat() + "Z",
        "captured_with": {
            "tool": _BUNDLE_TOOL,
            "browser_backend": _safe_backend_name(),
            "headless": bool(headless),
            "dwell_seconds": int(dwell_seconds or 0),
        },
        "browser": {
            "profile_dir": profile_dir,
            "final_url": final_url or site_url,
            "title": title or "",
        },
        "cookies": cookie_items,
        "storage_state": filtered_storage_state(storage_state, site_host),
        "security": {
            "sensitive": True,
            "hint": "This file contains reusable login cookies. Keep it private and delete it after import.",
        },
    }


async def export_auth_bundle(
    *,
    site_url: str,
    output_path: str | Path,
    profile_dir: str | Path | None = None,
    headless: bool = False,
    dwell_seconds: int = 300,
    name: str | None = None,
) -> dict[str, Any]:
    """Open a browser, let the user log in, and write an Auth Bundle file."""
    if not playwright_enabled():
        raise PlaywrightDisabledError("Auth Bundle export requires Playwright (PIM_FEATURE_PLAYWRIGHT=true).")
    if not headless:
        _require_headful_display()

    site_host = normalize_host(site_url)
    if not site_host:
        raise AuthBundleError("Invalid site_url; cannot resolve host")
    resolved_profile_dir = Path(profile_dir).expanduser() if profile_dir else _default_export_profile_dir(site_host)
    resolved_profile_dir.mkdir(parents=True, exist_ok=True)

    capture = await _capture_browser_state(
        site_url=site_url,
        user_data_dir=str(resolved_profile_dir),
        headless=headless,
        dwell_seconds=dwell_seconds,
    )
    bundle = build_auth_bundle(
        site_url=site_url,
        cookies=capture.get("cookies") or [],
        storage_state=capture.get("storage_state"),
        final_url=capture.get("final_url"),
        title=capture.get("title"),
        profile_dir=str(resolved_profile_dir),
        headless=headless,
        dwell_seconds=dwell_seconds,
        name=name,
    )
    write_auth_bundle(output_path, bundle)
    return bundle


def _default_export_profile_dir(site_host: str) -> Path:
    suffix = utcnow_naive().strftime("%Y%m%d%H%M%S")
    return profiles_root().parent / "auth-bundle-profiles" / f"{slugify_profile_name(site_host)}-{suffix}"


def _require_headful_display() -> None:
    if not sys.platform.startswith("linux"):
        return
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return
    raise AuthBundleError(_HEADFUL_LINUX_DISPLAY_ERROR)


async def _capture_browser_state(
    *,
    site_url: str,
    user_data_dir: str,
    headless: bool,
    dwell_seconds: int,
) -> dict[str, Any]:
    launch_kwargs: dict[str, Any] = {
        "user_data_dir": user_data_dir,
        "headless": bool(headless),
        "args": recommended_launch_args([]),
    }
    channel = default_channel()
    if channel:
        launch_kwargs["channel"] = channel
    if is_patchright_active():
        launch_kwargs["no_viewport"] = True
    else:
        launch_kwargs["user_agent"] = _BROWSER_USER_AGENT

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(**launch_kwargs)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            if not is_patchright_active():
                await page.add_init_script(stealth_init_script())

            try:
                await page.goto(site_url, wait_until="domcontentloaded", timeout=45000)
            except timeout_error_types():
                if headless:
                    raise

            holder: dict[str, Any] = {"cookies": [], "storage_state": None}
            await _snapshot_context_state(context, holder)
            if headless:
                if dwell_seconds > 0:
                    await page.wait_for_timeout(dwell_seconds * 1000)
                    await _snapshot_context_state(context, holder)
            else:
                await _wait_for_user_done(context, holder, dwell_seconds)

            await _snapshot_context_state(context, holder)
            final_url = page.url if not page.is_closed() else site_url
            title = "" if page.is_closed() else await page.title()
            return {
                "final_url": final_url,
                "title": title,
                "cookies": holder.get("cookies") or [],
                "storage_state": holder.get("storage_state"),
            }
        finally:
            with contextlib.suppress(BaseException):
                await context.close()


async def _wait_for_user_done(context, holder: dict[str, Any], dwell_seconds: int) -> None:
    timeout_s = max(int(dwell_seconds or 0), 30)
    close_event = asyncio.Event()
    context.on("close", lambda *_: close_event.set())
    for page in list(context.pages):
        page.on("close", lambda *_: close_event.set())
    context.on("page", lambda page: page.on("close", lambda *_: close_event.set()))

    async def poll_state() -> None:
        try:
            while True:
                await asyncio.sleep(1.5)
                await _snapshot_context_state(context, holder)
        except asyncio.CancelledError:
            await _snapshot_context_state(context, holder)
            raise

    async def poll_pages() -> None:
        await asyncio.sleep(2)
        while True:
            await asyncio.sleep(1.5)
            open_pages = [page for page in context.pages if not page.is_closed()]
            if not open_pages:
                return

    state_task = asyncio.create_task(poll_state())
    close_task = asyncio.create_task(close_event.wait())
    pages_task = asyncio.create_task(poll_pages())
    try:
        done, pending = await asyncio.wait(
            {close_task, pages_task},
            timeout=timeout_s,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done:
            return
        for task in pending:
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
    finally:
        state_task.cancel()
        with contextlib.suppress(BaseException):
            await state_task


async def _snapshot_context_state(context, holder: dict[str, Any]) -> None:
    with contextlib.suppress(BaseException):
        holder["cookies"] = await context.cookies()
    with contextlib.suppress(BaseException):
        holder["storage_state"] = await context.storage_state()


def _filter_cookie_items(raw_items: Any, site_host: str) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        value = item.get("value")
        domain = str(item.get("domain") or item.get("host") or "").strip().lstrip(".").lower()
        if not name or value is None:
            continue
        if domain and site_host and not host_matches(site_host, domain):
            continue
        cleaned.append(_public_cookie_item(item, fallback_domain=site_host))
    return cleaned


def _public_cookie_item(item: dict[str, Any], *, fallback_domain: str) -> dict[str, Any]:
    allowed = {
        "name",
        "value",
        "domain",
        "path",
        "expires",
        "httpOnly",
        "secure",
        "sameSite",
    }
    out = {key: item[key] for key in allowed if key in item}
    out["name"] = str(out.get("name") or "")
    out["value"] = str(out.get("value") or "")
    out["domain"] = str(out.get("domain") or fallback_domain)
    out["path"] = str(out.get("path") or "/")
    return out


def _safe_backend_name() -> str:
    with contextlib.suppress(RuntimeError, ImportError):
        return backend_name()
    return "unknown"
