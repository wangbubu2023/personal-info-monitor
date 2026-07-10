use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use std::fs::File;
use std::io::Write;
use std::path::{Path, PathBuf};
use tauri::{Manager, Url, WebviewUrl, WebviewWindowBuilder};
use zip::write::FileOptions;

const CAPTURE_WINDOW_LABEL: &str = "auth-capture";

#[derive(Debug, Deserialize)]
struct ExportBundleInput {
    name: String,
    site_host: String,
    bundle: Value,
}

#[derive(Debug, Serialize)]
struct CaptureResult {
    bundle: Value,
    site_host: String,
    name: String,
}

#[derive(Debug, Serialize)]
struct CaptureStarted {
    site_url: String,
    site_host: String,
}

#[derive(Debug, Serialize)]
struct ExportResult {
    path: String,
    profile_count: usize,
}

fn parse_site_url(value: &str) -> Result<(Url, String), String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return Err("站点 URL 不能为空".into());
    }
    let normalized = if trimmed.contains("://") {
        trimmed.to_string()
    } else {
        format!("https://{trimmed}")
    };
    let url = Url::parse(&normalized).map_err(|e| format!("站点 URL 无效: {e}"))?;
    if !matches!(url.scheme(), "http" | "https") {
        return Err("站点 URL 只支持 http 或 https".into());
    }
    let site_host = url
        .host_str()
        .map(normalize_host)
        .filter(|host| !host.is_empty())
        .ok_or_else(|| "站点 URL 缺少有效域名".to_string())?;
    Ok((url, site_host))
}

fn normalize_host(value: &str) -> String {
    let host = value
        .trim()
        .trim_start_matches('.')
        .trim_end_matches('.')
        .to_ascii_lowercase();
    host.strip_prefix("www.").unwrap_or(&host).to_string()
}

fn host_matches(left: &str, right: &str) -> bool {
    let left = normalize_host(left);
    let right = normalize_host(right);
    !left.is_empty()
        && !right.is_empty()
        && (left == right
            || left.ends_with(&format!(".{right}"))
            || right.ends_with(&format!(".{left}")))
}

fn safe_file_stem(value: &str) -> String {
    let stem: String = value
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == '-' || ch == '_' || ch == '.' {
                ch
            } else {
                '_'
            }
        })
        .collect();
    let trimmed = stem.trim_matches('_');
    if trimmed.is_empty() {
        "profile".to_string()
    } else {
        trimmed.to_string()
    }
}

fn output_dir(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .download_dir()
        .or_else(|_| app.path().app_data_dir())
        .map_err(|e| format!("cannot resolve output dir: {e}"))?
        .join("PIM Auth Assistant");
    std::fs::create_dir_all(&dir)
        .map_err(|e| format!("create output dir {}: {e}", dir.display()))?;
    Ok(dir)
}

#[tauri::command]
fn is_desktop_runtime() -> bool {
    true
}

#[tauri::command]
fn start_auth_capture(app: tauri::AppHandle, site_url: String) -> Result<CaptureStarted, String> {
    let (url, site_host) = parse_site_url(&site_url)?;
    if let Some(existing) = app.get_webview_window(CAPTURE_WINDOW_LABEL) {
        existing
            .close()
            .map_err(|e| format!("关闭旧采集窗口失败: {e}"))?;
    }

    WebviewWindowBuilder::new(
        &app,
        CAPTURE_WINDOW_LABEL,
        WebviewUrl::External(url.clone()),
    )
    .title(format!("登录 {site_host} · PIM Auth Assistant"))
    .inner_size(1100.0, 780.0)
    .min_inner_size(760.0, 560.0)
    .center()
    .build()
    .map_err(|e| format!("打开登录窗口失败: {e}"))?;

    Ok(CaptureStarted {
        site_url: url.to_string(),
        site_host,
    })
}

fn cookie_to_json(cookie: &tauri::webview::Cookie<'_>, fallback_domain: &str) -> Value {
    let mut item = Map::new();
    item.insert("name".into(), Value::String(cookie.name().to_string()));
    item.insert("value".into(), Value::String(cookie.value().to_string()));
    item.insert(
        "domain".into(),
        Value::String(cookie.domain().unwrap_or(fallback_domain).to_string()),
    );
    item.insert(
        "path".into(),
        Value::String(cookie.path().unwrap_or("/").to_string()),
    );
    if let Some(value) = cookie.expires_datetime() {
        item.insert("expires".into(), Value::from(value.unix_timestamp()));
    }
    if let Some(value) = cookie.http_only() {
        item.insert("httpOnly".into(), Value::Bool(value));
    }
    if let Some(value) = cookie.secure() {
        item.insert("secure".into(), Value::Bool(value));
    }
    if let Some(value) = cookie.same_site() {
        item.insert("sameSite".into(), Value::String(format!("{value:?}")));
    }
    Value::Object(item)
}

#[tauri::command]
async fn finish_auth_capture(
    app: tauri::AppHandle,
    site_url: String,
) -> Result<CaptureResult, String> {
    let (site_url, site_host) = parse_site_url(&site_url)?;
    let window = app
        .get_webview_window(CAPTURE_WINDOW_LABEL)
        .ok_or_else(|| "登录窗口已关闭，请重新开始采集".to_string())?;
    let final_url = window
        .url()
        .map(|url| url.to_string())
        .unwrap_or_else(|_| site_url.to_string());
    let cookies = window
        .cookies()
        .map_err(|e| format!("读取登录 Cookie 失败: {e}"))?
        .into_iter()
        .filter(|cookie| {
            cookie
                .domain()
                .map(|domain| host_matches(&site_host, domain))
                .unwrap_or(true)
        })
        .map(|cookie| cookie_to_json(&cookie, &site_host))
        .collect::<Vec<_>>();

    if cookies.is_empty() {
        return Err(format!(
            "没有读取到 {site_host} 的 Cookie。请确认已完成登录，再点击“完成采集”。"
        ));
    }

    let created_at = time::OffsetDateTime::now_utc()
        .format(&time::format_description::well_known::Rfc3339)
        .unwrap_or_default();
    let bundle = json!({
        "kind": "pim.auth_bundle",
        "version": 1,
        "name": format!("{site_host} Auth Bundle"),
        "site_url": site_url.to_string(),
        "site_host": site_host.clone(),
        "created_at": created_at,
        "captured_with": {
            "tool": "pim-auth-assistant",
            "browser_backend": "tauri-webview",
            "headless": false
        },
        "browser": {
            "profile_dir": null,
            "final_url": final_url,
            "title": ""
        },
        "cookies": cookies,
        "storage_state": {
            "cookies": cookies,
            "origins": []
        },
        "security": {
            "sensitive": true,
            "hint": "This bundle contains reusable login cookies. Keep it private and delete it after import."
        }
    });

    window
        .close()
        .map_err(|e| format!("关闭登录窗口失败: {e}"))?;

    Ok(CaptureResult {
        bundle,
        site_host: site_host.clone(),
        name: format!("{site_host} 登录态"),
    })
}

#[tauri::command]
fn cancel_auth_capture(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(CAPTURE_WINDOW_LABEL) {
        window
            .close()
            .map_err(|e| format!("关闭登录窗口失败: {e}"))?;
    }
    Ok(())
}

#[tauri::command]
fn export_auth_zip(
    app: tauri::AppHandle,
    bundles: Vec<ExportBundleInput>,
) -> Result<ExportResult, String> {
    if bundles.is_empty() {
        return Err("请选择至少一个登录态".into());
    }

    let dir = output_dir(&app)?;
    let timestamp = chrono_like_timestamp();
    let path = dir.join(format!("pim-auth-export-{timestamp}.zip"));
    write_auth_export_zip(&path, &bundles)?;
    Ok(ExportResult {
        path: path.display().to_string(),
        profile_count: bundles.len(),
    })
}

fn chrono_like_timestamp() -> String {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    now.to_string()
}

fn write_auth_export_zip(path: &Path, bundles: &[ExportBundleInput]) -> Result<(), String> {
    let file = File::create(path).map_err(|e| format!("create zip {}: {e}", path.display()))?;
    let mut zip = zip::ZipWriter::new(file);
    let options: FileOptions<'_, ()> =
        FileOptions::default().compression_method(zip::CompressionMethod::Deflated);

    let mut profiles = Vec::with_capacity(bundles.len());
    for (index, item) in bundles.iter().enumerate() {
        let file_name = format!(
            "profiles/{}-{}.auth.json",
            index + 1,
            safe_file_stem(&item.site_host)
        );
        profiles.push(serde_json::json!({
            "site_host": item.site_host,
            "name": item.name,
            "file": file_name,
        }));
        zip.start_file(&file_name, options)
            .map_err(|e| format!("zip start {file_name}: {e}"))?;
        let payload = serde_json::to_vec_pretty(&item.bundle)
            .map_err(|e| format!("serialize bundle: {e}"))?;
        zip.write_all(&payload)
            .map_err(|e| format!("write bundle {file_name}: {e}"))?;
    }

    let manifest = serde_json::json!({
        "kind": "pim.auth_export",
        "version": 1,
        "created_at": chrono_like_timestamp(),
        "profiles": profiles,
    });
    zip.start_file("manifest.json", options)
        .map_err(|e| format!("zip start manifest: {e}"))?;
    zip.write_all(
        &serde_json::to_vec_pretty(&manifest).map_err(|e| format!("serialize manifest: {e}"))?,
    )
    .map_err(|e| format!("write manifest: {e}"))?;
    zip.finish().map_err(|e| format!("finish zip: {e}"))?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            is_desktop_runtime,
            start_auth_capture,
            finish_auth_capture,
            cancel_auth_capture,
            export_auth_zip
        ])
        .build(tauri::generate_context!())
        .expect("error while building PIM Auth Assistant")
        .run(|_app_handle, _event| {});
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_bare_host_and_normalizes_www() {
        let (url, host) = parse_site_url("www.Example.com/login").expect("valid URL");
        assert_eq!(url.as_str(), "https://www.example.com/login");
        assert_eq!(host, "example.com");
    }

    #[test]
    fn host_matching_accepts_parent_cookie_domains() {
        assert!(host_matches("x.com", ".x.com"));
        assert!(host_matches("www.nytimes.com", "nytimes.com"));
        assert!(!host_matches("example.com", "example.org"));
    }

    #[test]
    fn serializes_webview_cookie_for_pim_bundle_contract() {
        let cookie = tauri::webview::Cookie::parse(
            "session=secret; Domain=.example.com; Path=/; HttpOnly; Secure; SameSite=Lax",
        )
        .expect("valid cookie");
        let value = cookie_to_json(&cookie, "example.com");

        assert_eq!(value["name"], "session");
        assert_eq!(value["value"], "secret");
        assert_eq!(value["domain"], "example.com");
        assert_eq!(value["path"], "/");
        assert_eq!(value["httpOnly"], true);
        assert_eq!(value["secure"], true);
        assert_eq!(value["sameSite"], "Lax");
    }
}
