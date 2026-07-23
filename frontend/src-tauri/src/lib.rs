//! Tauri shell: start/stop local backend (single uvicorn process) when the desktop app runs.

use keyring::Entry;
use serde::{Deserialize, Serialize};
use std::io::Read;
use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Manager, RunEvent};

/// Child processes we spawned (killed on app exit).
struct BackendState {
    children: Mutex<Vec<Child>>,
}

fn resolve_project_root() -> Result<PathBuf, String> {
    if let Ok(p) = std::env::var("PIM_PROJECT_ROOT") {
        let pb = PathBuf::from(p.trim());
        return pb
            .canonicalize()
            .map_err(|e| format!("PIM_PROJECT_ROOT invalid: {e}"));
    }
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest
        .join("../..")
        .canonicalize()
        .map_err(|e| format!("Cannot resolve repo root from CARGO_MANIFEST_DIR: {e}"))
}

fn find_python(backend: &Path) -> Result<PathBuf, String> {
    for rel in [
        ".venv/bin/python3",
        ".venv/bin/python",
        "venv/bin/python3",
        "venv/bin/python",
    ] {
        let cand = backend.join(rel);
        if cand.is_file() {
            return Ok(cand);
        }
    }
    Err("未找到 backend 虚拟环境。请在项目根目录执行: ./pim setup".into())
}

fn backend_port() -> u16 {
    std::env::var("PIM_PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(8000)
}

fn port_open(port: u16) -> bool {
    TcpStream::connect_timeout(
        &format!("127.0.0.1:{port}").parse().unwrap(),
        Duration::from_millis(250),
    )
    .is_ok()
}

fn wait_for_backend(port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    let url = format!("http://127.0.0.1:{port}/livez");
    while Instant::now() < deadline {
        if let Ok(resp) = ureq::get(&url).call() {
            if resp.status() == 200 {
                return true;
            }
        }
        std::thread::sleep(Duration::from_millis(400));
    }
    false
}

fn backend_healthy(port: u16) -> bool {
    let url = format!("http://127.0.0.1:{port}/livez");
    matches!(ureq::get(&url).call(), Ok(resp) if resp.status() == 200)
}

fn spawn_child(
    python: &Path,
    cwd: &Path,
    module: &str,
    args: &[&str],
    log_path: &Path,
) -> Result<Child, String> {
    let log = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_path)
        .map_err(|e| format!("open log {}: {e}", log_path.display()))?;

    let mut cmd = Command::new(python);
    cmd.current_dir(cwd)
        .arg("-m")
        .arg(module)
        .args(args)
        .stdout(Stdio::from(log.try_clone().map_err(|e| e.to_string())?))
        .stderr(Stdio::from(log))
        .env("PYTHONUNBUFFERED", "1");
    cmd.spawn().map_err(|e| format!("spawn failed: {e}"))
}

fn start_backend_stack(app: &AppHandle) -> Result<(), String> {
    if std::env::var("PIM_SKIP_BACKEND").unwrap_or_default() == "1" {
        eprintln!("[pim-tauri] PIM_SKIP_BACKEND=1 — 不启动后端");
        return Ok(());
    }

    let root = resolve_project_root()?;
    let backend = root.join("backend");
    if !backend.is_dir() {
        return Err(format!("backend 目录不存在: {}", backend.display()));
    }

    let python = find_python(&backend)?;
    let port = backend_port();
    let port_str = port.to_string();
    let logs = root.join(".pim-tauri-logs");
    std::fs::create_dir_all(&logs).map_err(|e| e.to_string())?;

    let state = app.state::<BackendState>();
    let mut children = state.children.lock().map_err(|e| e.to_string())?;

    if port_open(port) {
        if backend_healthy(port) {
            eprintln!("[pim-tauri] 后端已在端口 {port} 运行 — 复用现有实例");
        } else {
            return Err(
                format!(
                    "端口 {port} 已被其他进程占用，且 /livez 不可用。请停止占用进程，或设置 PIM_PORT 指向空闲端口。"
                )
            );
        }
    } else {
        // Single process: uvicorn with APScheduler (no Celery/Redis needed)
        let ch = spawn_child(
            &python,
            &backend,
            "uvicorn",
            &["app.main:app", "--host", "127.0.0.1", "--port", &port_str],
            &logs.join("uvicorn.log"),
        )?;
        children.push(ch);
        eprintln!("[pim-tauri] 已启动 uvicorn (port {port})");
    }

    drop(children);

    if !wait_for_backend(port, Duration::from_secs(30)) {
        return Err(
            "后端在 30 秒内未就绪。请确认 backend/.env 配置正确。日志: .pim-tauri-logs/uvicorn.log"
                .into(),
        );
    }
    eprintln!("[pim-tauri] 后端健康检查通过");
    Ok(())
}

fn stop_backend_stack(app: &AppHandle) {
    let Some(state) = app.try_state::<BackendState>() else {
        return;
    };
    let Ok(mut children) = state.children.lock() else {
        return;
    };
    for mut child in children.drain(..) {
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn read_api_key(app: &AppHandle) -> Result<Option<String>, String> {
    let entry = Entry::new("pim", "api_key").map_err(|e| format!("keyring init failed: {e}"))?;
    match entry.get_password() {
        Ok(value) => {
            let trimmed = value.trim().to_string();
            if trimmed.is_empty() {
                Ok(None)
            } else {
                Ok(Some(trimmed))
            }
        }
        Err(keyring::Error::NoEntry) => {
            // 尝试从旧明文文件迁移，错误直接传播
            migrate_from_legacy_file(&app, &entry)
        }
        Err(e) => Err(format!("读取 API Key 失败: {e}")),
    }
}

#[tauri::command]
fn has_api_key(app: AppHandle) -> Result<bool, String> {
    Ok(read_api_key(&app)?.is_some())
}

/// 从旧的 secrets/pim_api_key 文件读取，写入 Keychain，删除文件。
fn migrate_from_legacy_file(app: &AppHandle, entry: &Entry) -> Result<Option<String>, String> {
    let base = app
        .path()
        .app_config_dir()
        .map_err(|e| format!("cannot get config dir: {e}"))?;
    let legacy = base.join("secrets").join("pim_api_key");
    if !legacy.exists() {
        return Ok(None);
    }
    let raw = std::fs::read_to_string(&legacy).map_err(|e| format!("read legacy key: {e}"))?;
    let trimmed = raw.trim().to_string();
    if trimmed.is_empty() {
        let _ = std::fs::remove_file(&legacy);
        return Ok(None);
    }
    entry
        .set_password(&trimmed)
        .map_err(|e| format!("migrate to keyring: {e}"))?;
    let _ = std::fs::remove_file(&legacy);
    eprintln!("[pim-tauri] API Key 已从旧文件迁移到系统 Keychain");
    Ok(Some(trimmed))
}

#[tauri::command]
fn set_api_key(_app: AppHandle, value: String) -> Result<(), String> {
    let trimmed = value.trim().to_string();
    if trimmed.is_empty() {
        return Err("API Key 不能为空".into());
    }
    let entry = Entry::new("pim", "api_key").map_err(|e| format!("keyring init failed: {e}"))?;
    entry
        .set_password(&trimmed)
        .map_err(|e| format!("写入 API Key 失败: {e}"))
}

#[tauri::command]
fn clear_api_key(_app: AppHandle) -> Result<(), String> {
    let entry = Entry::new("pim", "api_key").map_err(|e| format!("keyring init failed: {e}"))?;
    match entry.delete_credential() {
        Ok(()) => Ok(()),
        Err(keyring::Error::NoEntry) => Ok(()),
        Err(e) => Err(format!("清除 API Key 失败: {e}")),
    }
}

#[derive(Deserialize)]
struct ApiProxyRequest {
    method: String,
    path: String,
    body: Option<String>,
}

#[derive(Serialize)]
struct ApiProxyResponse {
    status: u16,
    content_type: Option<String>,
    body: String,
}

fn validate_api_path(raw: &str) -> Result<&str, String> {
    let path = raw.trim();
    let path_only = path.split('?').next().unwrap_or(path);
    let encoded_path = path_only.to_ascii_lowercase();
    if !path_only.starts_with("/api/")
        || path.contains("://")
        || path.contains('#')
        || path.contains('\\')
        || path.contains('\r')
        || path.contains('\n')
        || path_only.split('/').any(|segment| segment == "..")
        || encoded_path.contains("%2e")
        || encoded_path.contains("%2f")
        || encoded_path.contains("%5c")
        || path.len() > 8192
    {
        return Err("API proxy path is outside the permitted /api surface".into());
    }
    Ok(path)
}

#[cfg(test)]
mod tests {
    use super::validate_api_path;

    #[test]
    fn restricted_proxy_accepts_only_api_paths() {
        assert_eq!(
            validate_api_path("/api/contents?page=1").unwrap(),
            "/api/contents?page=1"
        );
        assert!(validate_api_path("https://evil.example/api/contents").is_err());
        assert!(validate_api_path("/livez").is_err());
        assert!(validate_api_path("/api/../livez").is_err());
        assert!(validate_api_path("/api/%2e%2e/livez").is_err());
    }
}

/// Restricted loopback proxy. The renderer supplies only an API path and
/// payload; the long-lived credential is read and attached inside Rust.
#[tauri::command]
fn api_request(app: AppHandle, request: ApiProxyRequest) -> Result<ApiProxyResponse, String> {
    let method = request.method.trim().to_ascii_uppercase();
    if !matches!(method.as_str(), "GET" | "POST" | "PUT" | "PATCH" | "DELETE") {
        return Err("API proxy method is not permitted".into());
    }
    let path = validate_api_path(&request.path)?;
    if request
        .body
        .as_ref()
        .map_or(false, |body| body.len() > 10 * 1024 * 1024)
    {
        return Err("API proxy request body exceeds 10 MiB".into());
    }
    let api_key = read_api_key(&app)?.ok_or_else(|| "API Key 尚未配置".to_string())?;
    let url = format!("http://127.0.0.1:{}{}", backend_port(), path);
    let agent = ureq::AgentBuilder::new()
        .redirects(0)
        .timeout(Duration::from_secs(130))
        .build();
    let mut outbound = agent.request(&method, &url).set("X-API-Key", &api_key).set(
        "Accept",
        "application/json, application/x-ndjson, text/plain, */*",
    );
    if request.body.is_some() {
        outbound = outbound.set("Content-Type", "application/json");
    }
    let result = match request.body {
        Some(body) => outbound.send_string(&body),
        None => outbound.call(),
    };
    let response = match result {
        Ok(response) => response,
        Err(ureq::Error::Status(_, response)) => response,
        Err(error) => return Err(format!("API proxy transport failed: {error}")),
    };
    let status = response.status();
    let content_type = response.header("Content-Type").map(str::to_string);
    let mut body = String::new();
    response
        .into_reader()
        .take(20 * 1024 * 1024)
        .read_to_string(&mut body)
        .map_err(|error| format!("API proxy response read failed: {error}"))?;
    Ok(ApiProxyResponse {
        status,
        content_type,
        body,
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(BackendState {
            children: Mutex::new(Vec::new()),
        })
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                if let Err(e) = start_backend_stack(&handle) {
                    eprintln!("[pim-tauri] 启动后端失败: {e}");
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            has_api_key,
            set_api_key,
            clear_api_key,
            api_request
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::Exit = event {
                stop_backend_stack(app_handle);
            }
        });
}
