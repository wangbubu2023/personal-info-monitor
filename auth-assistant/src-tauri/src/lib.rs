use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs::File;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;
use tauri::Manager;
use zip::write::FileOptions;

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
struct ExportResult {
    path: String,
    profile_count: usize,
}

fn resolve_repo_root() -> Result<PathBuf, String> {
    if let Ok(raw) = std::env::var("PIM_PROJECT_ROOT") {
        let trimmed = raw.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed)
                .canonicalize()
                .map_err(|e| format!("PIM_PROJECT_ROOT invalid: {e}"));
        }
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .map_err(|e| format!("Cannot resolve repo root: {e}"))
}

fn host_from_bundle(bundle: &Value) -> String {
    bundle
        .get("site_host")
        .and_then(Value::as_str)
        .filter(|s| !s.trim().is_empty())
        .map(|s| s.trim().to_string())
        .unwrap_or_else(|| "unknown-host".to_string())
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
    std::fs::create_dir_all(&dir).map_err(|e| format!("create output dir {}: {e}", dir.display()))?;
    Ok(dir)
}

#[tauri::command]
fn is_desktop_runtime() -> bool {
    true
}

#[tauri::command]
fn capture_auth_bundle(site_url: String, dwell_seconds: Option<u64>) -> Result<CaptureResult, String> {
    let trimmed = site_url.trim();
    if trimmed.is_empty() {
        return Err("站点 URL 不能为空".into());
    }

    let repo_root = resolve_repo_root()?;
    let pim = repo_root.join("pim");
    if !pim.is_file() {
        return Err(format!(
            "未找到 PIM CLI: {}。开发模式请设置 PIM_PROJECT_ROOT 指向 personal-info-monitor 根目录。",
            pim.display()
        ));
    }

    let temp = tempfile::Builder::new()
        .prefix("pim-auth-assistant-")
        .suffix(".json")
        .tempfile()
        .map_err(|e| format!("create temp auth bundle: {e}"))?;
    let out_path = temp.path().to_path_buf();

    let mut command = Command::new(&pim);
    command
        .current_dir(&repo_root)
        .arg("capture-session")
        .arg(trimmed)
        .arg("--out")
        .arg(&out_path);
    if let Some(seconds) = dwell_seconds.filter(|v| *v > 0) {
        command.arg("--dwell-seconds").arg(seconds.to_string());
    }

    let status = command
        .status()
        .map_err(|e| format!("启动浏览器采集失败: {e}"))?;
    if !status.success() {
        return Err(format!("浏览器采集失败，退出码: {status}"));
    }

    let raw = std::fs::read_to_string(&out_path)
        .map_err(|e| format!("读取采集结果失败 {}: {e}", out_path.display()))?;
    let bundle: Value = serde_json::from_str(&raw).map_err(|e| format!("采集结果不是合法 JSON: {e}"))?;
    if bundle.get("kind").and_then(Value::as_str) != Some("pim.auth_bundle") {
        return Err("采集结果不是 pim.auth_bundle".into());
    }
    let site_host = host_from_bundle(&bundle);
    let name = bundle
        .get("name")
        .and_then(Value::as_str)
        .filter(|s| !s.trim().is_empty())
        .map(|s| s.trim().to_string())
        .unwrap_or_else(|| format!("{site_host} 登录态"));

    Ok(CaptureResult {
        bundle,
        site_host,
        name,
    })
}

#[tauri::command]
fn export_auth_zip(app: tauri::AppHandle, bundles: Vec<ExportBundleInput>) -> Result<ExportResult, String> {
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
    let options: FileOptions<'_, ()> = FileOptions::default().compression_method(zip::CompressionMethod::Deflated);

    let mut profiles = Vec::with_capacity(bundles.len());
    for (index, item) in bundles.iter().enumerate() {
        let file_name = format!("profiles/{}-{}.auth.json", index + 1, safe_file_stem(&item.site_host));
        profiles.push(serde_json::json!({
            "site_host": item.site_host,
            "name": item.name,
            "file": file_name,
        }));
        zip.start_file(&file_name, options)
            .map_err(|e| format!("zip start {file_name}: {e}"))?;
        let payload = serde_json::to_vec_pretty(&item.bundle).map_err(|e| format!("serialize bundle: {e}"))?;
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
            capture_auth_bundle,
            export_auth_zip
        ])
        .build(tauri::generate_context!())
        .expect("error while building PIM Auth Assistant")
        .run(|_app_handle, _event| {});
}
