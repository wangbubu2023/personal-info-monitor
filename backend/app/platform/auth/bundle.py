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
import re
import select
import sys
from pathlib import Path
from typing import Any

from app.features import PlaywrightDisabledError, playwright_enabled
from app.platform.browser.playwright_runtime import timeout_error_types
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
_AUTH_BUNDLE_DONE_URL = "https://pim.local/auth-bundle-captured"
_AUTH_BUNDLE_DONE_HTML = """
<!doctype html>
<meta charset="utf-8">
<title>PIM Auth Bundle captured</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 32px; color: #172033; }
  code { background: #f2f4f7; border-radius: 6px; padding: 2px 6px; }
</style>
<h1>登录态已准备导出</h1>
<p>你可以回到终端，等待命令写出 Auth Bundle 文件。</p>
<p>如果窗口没有自动关闭，请手动关闭这个浏览器窗口。</p>
"""


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
    launch_kwargs = _browser_launch_kwargs(headless=headless)
    context_kwargs = _browser_context_kwargs(user_data_dir=user_data_dir)
    _print_capture_diagnostics(
        site_url=site_url,
        user_data_dir=user_data_dir,
        launch_kwargs=launch_kwargs,
        context_kwargs=context_kwargs,
    )

    async with _auth_bundle_playwright() as p:
        browser = await p.chromium.launch(**launch_kwargs)
        try:
            browser_version = browser.version
        except (AttributeError, TypeError):
            browser_version = "unknown"
        print(f"Browser version: {browser_version}")
        context = await browser.new_context(**context_kwargs)
        try:
            await context.route(_AUTH_BUNDLE_DONE_URL, _fulfill_auth_bundle_done)
            if _should_block_google_login_popups(site_url):
                await _install_x_login_popup_blockers(context)
            _attach_context_debug_listeners(context)
            page = await context.new_page()
            _attach_page_debug_listeners(page, "main")
            await page.bring_to_front()

            navigation_url = _initial_capture_url(site_url)
            print(f"Initial navigation URL: {navigation_url}")
            try:
                await page.goto(navigation_url, wait_until="domcontentloaded", timeout=45000)
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
                await _wait_for_user_done(context, page, holder, dwell_seconds)

            await _snapshot_context_state(context, holder)
            await _persist_storage_state(user_data_dir, holder.get("storage_state"))
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
            with contextlib.suppress(BaseException):
                await browser.close()


def _auth_bundle_playwright():
    # Auth Bundle capture is intentionally isolated from PIM's default browser
    # backend. The fetcher prefers patchright for anti-bot scraping, but users
    # reported patchright/system Chrome repeatedly opening and closing tabs while
    # manually logging in to x.com. Use stock Playwright's bundled Chromium here
    # unless the user explicitly opts back into another backend outside this flow.
    from playwright.async_api import async_playwright as stock_async_playwright  # type: ignore

    return stock_async_playwright()


def _browser_launch_kwargs(*, headless: bool) -> dict[str, Any]:
    return {
        "headless": bool(headless),
        "args": ["--disable-blink-features=AutomationControlled"],
    }


def _browser_context_kwargs(*, user_data_dir: str) -> dict[str, Any]:
    return {
        "locale": "zh-CN",
        "storage_state": _storage_state_path(user_data_dir),
    }


def _initial_capture_url(site_url: str) -> str:
    site_host = normalize_host(site_url)
    if site_host in {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}:
        return "https://x.com/i/flow/login"
    return site_url


def _should_block_google_login_popups(site_url: str) -> bool:
    site_host = normalize_host(site_url)
    return site_host in {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}


async def _install_x_login_popup_blockers(context) -> None:
    # X's login page eagerly loads Google Sign-In/FedCM widgets. In Playwright's
    # bundled Chromium those widgets may repeatedly open accounts.google.com
    # popups and steal focus before the user can type an X username/password.
    # For auth-bundle capture we want the native X login form, so block only the
    # Google identity surfaces and leave x.com itself untouched.
    print("X login guard: blocking Google Sign-In popups during manual capture.")
    google_identity_url = re.compile(r"^https://(?:accounts|play)\.google\.com/(?:gsi|v3/signin|signin|log)")
    await context.route(google_identity_url, _abort_x_google_identity_request)
    await context.add_init_script(
        """
(() => {
  const blockedHosts = new Set(['accounts.google.com', 'play.google.com']);
  const originalOpen = window.open;
  window.open = function(url, target, features) {
    try {
      const candidate = new URL(String(url || ''), window.location.href);
      if (blockedHosts.has(candidate.hostname)) {
        console.info('[pim-auth-bundle] blocked Google login popup', candidate.href);
        return null;
      }
    } catch (_) {}
    return originalOpen.call(window, url, target, features);
  };
})();
"""
    )


async def _abort_x_google_identity_request(route) -> None:
    print(f"[browser-debug] blocked Google identity request url={route.request.url}")
    await route.abort()


def _attach_context_debug_listeners(context) -> None:
    def on_page(new_page) -> None:
        label = f"page-{len(context.pages)}"
        print(f"[browser-debug] page created label={label} url={new_page.url}")
        _attach_page_debug_listeners(new_page, label)

    context.on("page", on_page)


def _attach_page_debug_listeners(page, label: str) -> None:
    page.on("close", lambda *_: print(f"[browser-debug] page closed label={label}"))
    page.on("crash", lambda *_: print(f"[browser-debug] page crashed label={label}"))
    page.on(
        "framenavigated",
        lambda frame: print(f"[browser-debug] navigated label={label} url={frame.url}")
        if frame == page.main_frame
        else None,
    )
    page.on("popup", lambda popup: print(f"[browser-debug] popup label={label} url={popup.url}"))
    page.on(
        "requestfailed",
        lambda request: print(
            "[browser-debug] request failed "
            f"label={label} method={request.method} url={request.url} failure={request.failure}"
        ),
    )


def _print_capture_diagnostics(
    *,
    site_url: str,
    user_data_dir: str,
    launch_kwargs: dict[str, Any],
    context_kwargs: dict[str, Any],
) -> None:
    print()
    print("PIM Auth Bundle browser diagnostics")
    print("-----------------------------------")
    print(f"Site URL: {site_url}")
    print("Backend: stock playwright.async_api")
    print("Launch API: chromium.launch + browser.new_context")
    print(f"Headless: {launch_kwargs.get('headless')}")
    print(f"Channel: {launch_kwargs.get('channel') or '<bundled chromium>'}")
    print(f"Executable path: {launch_kwargs.get('executable_path') or '<playwright default>'}")
    print(f"Launch args: {launch_kwargs.get('args') or []}")
    print(f"Context locale: {context_kwargs.get('locale') or '<default>'}")
    print(f"Context user agent: {context_kwargs.get('user_agent') or '<browser default>'}")
    print(f"User data dir: {user_data_dir}")
    print(f"Storage state path: {context_kwargs.get('storage_state') or '<none>'}")
    print(f"PIM_BROWSER_BACKEND env: {os.environ.get('PIM_BROWSER_BACKEND') or '<unset>'}")
    print(f"PIM_PLAYWRIGHT_CHANNEL env: {os.environ.get('PIM_PLAYWRIGHT_CHANNEL') or '<unset>'}")
    print(f"PIM_PLAYWRIGHT_NO_SANDBOX env: {os.environ.get('PIM_PLAYWRIGHT_NO_SANDBOX') or '<unset>'}")
    print()


def _storage_state_path(user_data_dir: str) -> str | None:
    path = Path(user_data_dir) / "storage_state.json"
    return str(path) if path.is_file() else None


async def _fulfill_auth_bundle_done(route) -> None:
    await route.fulfill(
        status=200,
        content_type="text/html; charset=utf-8",
        body=_AUTH_BUNDLE_DONE_HTML,
    )


async def _wait_for_user_done(context, page, holder: dict[str, Any], dwell_seconds: int) -> None:
    timeout_s = max(int(dwell_seconds or 0), 30)
    done_event = asyncio.Event()
    close_event = asyncio.Event()
    done_url_prefix = _AUTH_BUNDLE_DONE_URL.rstrip("/")
    stdin_available = sys.stdin.isatty()

    print()
    print("PIM Auth Bundle capture")
    print("-----------------------")
    print("请在打开的浏览器窗口完成登录。")
    print("完成后回到这个终端按 Enter，或直接关闭浏览器窗口。")
    print(f"最多等待 {timeout_s} 秒；期间不会自动刷新页面。")
    print()

    context.on("close", lambda *_: close_event.set())
    page.on("close", lambda *_: close_event.set())

    async def poll_state() -> None:
        try:
            while not done_event.is_set() and not close_event.is_set():
                await asyncio.sleep(2.0)
                await _snapshot_context_state(context, holder)
        except asyncio.CancelledError:
            await _snapshot_context_state(context, holder)
            raise

    async def poll_pages() -> None:
        await asyncio.sleep(1.0)
        while not done_event.is_set() and not close_event.is_set():
            await asyncio.sleep(1.0)
            open_pages = [candidate for candidate in context.pages if not candidate.is_closed()]
            if not open_pages:
                close_event.set()
                return
            if any((candidate.url or "").rstrip("/").startswith(done_url_prefix) for candidate in open_pages):
                done_event.set()
                return

    async def wait_for_enter() -> None:
        if not stdin_available:
            await asyncio.Event().wait()
            return
        while not done_event.is_set() and not close_event.is_set():
            readable, _, _ = await asyncio.to_thread(select.select, [sys.stdin], [], [], 0.25)
            if readable:
                sys.stdin.readline()
                done_event.set()
                return

    state_task = asyncio.create_task(poll_state())
    close_task = asyncio.create_task(close_event.wait())
    done_task = asyncio.create_task(done_event.wait())
    pages_task = asyncio.create_task(poll_pages())
    enter_task = asyncio.create_task(wait_for_enter())
    try:
        done, pending = await asyncio.wait(
            {close_task, done_task, pages_task, enter_task},
            timeout=timeout_s,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done and not page.is_closed():
            print("等待超时，正在导出当前浏览器登录态。")
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


async def _persist_storage_state(user_data_dir: str, storage_state: Any) -> None:
    if not isinstance(storage_state, dict):
        return
    path = Path(user_data_dir) / "storage_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_text, json.dumps(storage_state, ensure_ascii=False, indent=2), "utf-8")
    with contextlib.suppress(OSError):
        path.chmod(0o600)


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
    return "auth-bundle-playwright"
