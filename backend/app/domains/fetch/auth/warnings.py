"""Per-fetch auth/cookie diagnostics for the pipeline warning channel.

The collector stage attaches a small set of structured warnings to each fetch
result so the UI can show why a source produced 0 items or partial content.
Both entries in this module return ``(code, severity, message)`` tuples or
``None`` when there is nothing worth surfacing.

* ``auth_warning_entry`` — classifies a free-form ``auth_warning`` string
  (typically produced by login/refresh) into a stable code + severity.
* ``cookie_hydration_warning_entry`` — inspects ``source._runtime_fetch_diag``
  (set by the website collector) to summarise full-text hydration outcomes.
"""

from __future__ import annotations

from pathlib import Path

from app.utils.cookies import normalize_cookie_dict


def auth_warning_entry(auth_warning: str | None) -> tuple[str, str, str] | None:
    text = str(auth_warning or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if "captcha" in lowered or "challenge detected" in lowered or "人机" in lowered:
        return ("auth_captcha", "error", "登录受阻：检测到验证码/人机挑战")
    if text.startswith("自动登录失败"):
        return ("auth_login_failed", "error", text)
    if "手动 Cookie 优先模式" in text:
        return ("cookie_missing_manual_mode", "error", text)
    return ("auth_warning", "warning", text)


def cookie_hydration_warning_entry(source, runtime_auth: dict | None) -> tuple[str, str, str] | None:
    source_type = source.type.value if hasattr(source.type, "value") else str(source.type).lower()
    if source_type != "website":
        return None
    if not isinstance(runtime_auth, dict):
        return None
    creds = runtime_auth.get("credentials", {}) if isinstance(runtime_auth.get("credentials"), dict) else {}
    cookies = normalize_cookie_dict(creds.get("cookies"))
    browser_session = (
        runtime_auth.get("browser_session")
        if isinstance(runtime_auth.get("browser_session"), dict)
        else {}
    )
    has_browser_session = bool(str(browser_session.get("user_data_dir") or "").strip())
    raw_storage = str(browser_session.get("storage_state_path") or "").strip()
    has_storage_export = bool(raw_storage and Path(raw_storage).is_file())
    if not cookies and not has_browser_session and not has_storage_export:
        return None
    session_warning = str(browser_session.get("auth_warning") or "").strip()
    session_warning_entry = (
        ("browser_session_stale", "warning", session_warning)
        if session_warning and not browser_session.get("auth_ready")
        else None
    )

    diag = getattr(source, "_runtime_fetch_diag", None)
    if not isinstance(diag, dict):
        return session_warning_entry
    attempted = int(diag.get("attempted") or 0)
    hydrated = int(diag.get("hydrated") or 0)
    failures = diag.get("failures") if isinstance(diag.get("failures"), dict) else {}
    if attempted <= 0:
        return session_warning_entry
    if hydrated >= attempted:
        return session_warning_entry

    shell_fail = int(failures.get("shell_page", 0))
    wrapper_fail = int(failures.get("wrapper_unresolved", 0))
    if hydrated == 0:
        if shell_fail > 0:
            return (
                "fulltext_shell_page",
                "error",
                f"全文抓取失败：返回壳页面（可能 Cookie 失效或访问受限，尝试 {attempted} 篇）",
            )
        if wrapper_fail > 0:
            return (
                "fulltext_wrapper_unresolved",
                "warning",
                f"全文抓取受限：Google 包装链接未能解析为原文（尝试 {attempted} 篇）",
            )
        return (
            "fulltext_missing",
            "warning",
            f"全文抓取未命中：已尝试 {attempted} 篇，成功 0 篇",
        )

    return (
        "fulltext_partial",
        "warning",
        f"全文抓取部分成功：尝试 {attempted} 篇，成功 {hydrated} 篇",
    )
