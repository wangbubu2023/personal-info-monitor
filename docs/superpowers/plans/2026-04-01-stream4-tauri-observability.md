# Stream 4: Tauri Keychain/CSP + job_id 链路追踪 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Tauri 桌面端 API Key 从明文文件迁移到系统 Keychain，配置最小 CSP；在后台任务链路中注入 job_id，实现从抓取到处理的完整日志追踪。

**Architecture:** keyring crate 替换 fs 读写，三个 Tauri command（get/set/clear_api_key）签名不变，TypeScript 层零改动；logger.py 新增 job_id ContextVar 与 request_id 并列，fetch_source 生成 job_id 后通过 ContextVar 传播，task_queue 在 enqueue_process 时传递 job_id。

**Tech Stack:** Rust, Tauri 2, keyring crate 3.x, Python 3.14, contextvars

---

## 文件结构

```
frontend/src-tauri/
├── Cargo.toml                  # 新增 keyring = "3"
└── src/lib.rs                  # get/set/clear_api_key 改用 keyring，加迁移逻辑

frontend/src-tauri/tauri.conf.json   # csp: null → 最小策略字符串

backend/app/utils/logger.py          # 新增 job_id ContextVar + Filter + Formatter extra fields
backend/app/tasks/fetch_tasks.py     # fetch_source 入口注入 job_id
backend/app/tasks/process_tasks.py   # process_new_content 接收可选 job_id
backend/app/tasks/task_queue.py      # enqueue_process 传递 job_id（Task 9 已实现）
```

---

### Task 1: 更新 logger.py — 新增 job_id 支持

**Files:**
- Modify: `backend/app/utils/logger.py`
- Test: `backend/tests/test_logger_job_id.py`

- [ ] **Step 1: 写测试**

```python
# backend/tests/test_logger_job_id.py
import json
import logging
import pytest
from app.utils.logger import set_job_id, clear_job_id, get_job_id, get_logger


def test_set_and_get_job_id():
    set_job_id("abc123")
    assert get_job_id() == "abc123"
    clear_job_id()
    assert get_job_id() is None


def test_job_id_appears_in_json_log(caplog):
    set_job_id("job-xyz")
    logger = get_logger("test.job")
    with caplog.at_level(logging.INFO, logger="test.job"):
        logger.info("hello from job")
    clear_job_id()
    # caplog captures the record; check the attribute was set
    assert any(getattr(r, "job_id", None) == "job-xyz" for r in caplog.records)


def test_job_id_absent_when_not_set(caplog):
    clear_job_id()
    logger = get_logger("test.nojob")
    with caplog.at_level(logging.INFO, logger="test.nojob"):
        logger.info("no job here")
    assert all(getattr(r, "job_id", None) is None for r in caplog.records)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && ./.venv/bin/pytest tests/test_logger_job_id.py -v 2>&1 | tail -8
```

Expected: `ImportError: cannot import name 'set_job_id'`

- [ ] **Step 3: 更新 logger.py**

在 `backend/app/utils/logger.py` 中，在 `_request_id` 定义之后添加：

```python
_job_id: ContextVar[str | None] = ContextVar("job_id", default=None)


def set_job_id(job_id: str | None) -> None:
    """Bind the current background job id into logging context."""
    _job_id.set(job_id)


def clear_job_id() -> None:
    """Clear job-scoped logging context."""
    _job_id.set(None)


def get_job_id() -> str | None:
    """Return the active job id, if any."""
    return _job_id.get()
```

更新 `_RequestContextFilter.filter()` 方法：

```python
class _RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        record.job_id = get_job_id()
        return True
```

更新 `_JsonFormatter.format()` 方法，在 `request_id` 输出之后添加 `job_id` 和 extra fields 支持：

```python
class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        job_id = getattr(record, "job_id", None)
        if job_id:
            payload["job_id"] = job_id
        # Forward any extra structured fields (phase, source_id, etc.)
        for key in ("phase", "source_id", "content_id"):
            val = record.__dict__.get(key)
            if val is not None:
                payload[key] = val
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd backend && ./.venv/bin/pytest tests/test_logger_job_id.py -v 2>&1 | tail -8
```

Expected: `3 passed`

- [ ] **Step 5: 运行完整测试确认无回归**

```bash
cd backend && ./.venv/bin/pytest -q --no-header 2>&1 | tail -3
```

Expected: `passed`（数量与当前基线持平或增加）

- [ ] **Step 6: Commit**

```bash
git add backend/app/utils/logger.py backend/tests/test_logger_job_id.py
git commit -m "feat: logger.py 新增 job_id ContextVar 和 extra fields 支持"
```

---

### Task 2: fetch_tasks.py — 注入 job_id

**Files:**
- Modify: `backend/app/tasks/fetch_tasks.py:26-36`

- [ ] **Step 1: 更新 fetch_source 函数入口**

在 `backend/app/tasks/fetch_tasks.py` 中，在文件顶部的 imports 中添加：

```python
from uuid import uuid4
from app.utils.logger import set_job_id, clear_job_id
```

然后将 `fetch_source` 函数修改为：

```python
async def fetch_source(source_id: str, manual_trigger: bool = False):
    """Fetch content from a single source. Runs pipeline in a thread."""
    job_id = uuid4().hex
    set_job_id(job_id)
    logger.info(
        f"Starting fetch for source: {source_id} (manual={manual_trigger})",
        extra={"phase": "fetch", "source_id": source_id},
    )

    sem = get_fetch_semaphore()
    async with sem:
        await task_tracker.start_fetch()
        try:
            await _do_fetch(source_id, manual_trigger)
        finally:
            await task_tracker.end_fetch()
            clear_job_id()
```

- [ ] **Step 2: 运行测试确认无回归**

```bash
cd backend && ./.venv/bin/pytest -q --no-header 2>&1 | tail -3
```

Expected: 通过（数量不减少）

- [ ] **Step 3: Commit**

```bash
git add backend/app/tasks/fetch_tasks.py
git commit -m "feat: fetch_source 入口注入 job_id，贯穿抓取链路日志"
```

---

### Task 3: process_tasks.py — 接收和传递 job_id

**Files:**
- Modify: `backend/app/tasks/process_tasks.py:16-24`

- [ ] **Step 1: 更新 process_new_content 接受可选 job_id**

在 `backend/app/tasks/process_tasks.py` 顶部 imports 添加：

```python
from app.utils.logger import set_job_id, clear_job_id
```

将 `process_new_content` 函数签名改为：

```python
async def process_new_content(content_id: str, job_id: str | None = None):
    """Process a freshly saved content item (cookie full-text + keywords)."""
    if job_id:
        set_job_id(job_id)
    sem = get_llm_semaphore()
    async with sem:
        await task_tracker.start_process()
        try:
            await _process_new_content_async(content_id)
        finally:
            await task_tracker.end_process()
            if job_id:
                clear_job_id()
```

- [ ] **Step 2: 确认 task_queue.py 的 enqueue_process 已经传递 job_id（Task 9 已实现）**

```bash
grep -n "job_id" backend/app/tasks/task_queue.py
```

Expected: 找到 `enqueue_process(self, content_id: str, job_id: str | None = None)` 定义。

- [ ] **Step 3: 运行测试**

```bash
cd backend && ./.venv/bin/pytest -q --no-header 2>&1 | tail -3
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/tasks/process_tasks.py
git commit -m "feat: process_new_content 接收 job_id，继承抓取链路追踪上下文"
```

---

### Task 4: Cargo.toml — 添加 keyring 依赖

**Files:**
- Modify: `frontend/src-tauri/Cargo.toml`

- [ ] **Step 1: 添加 keyring 依赖**

在 `frontend/src-tauri/Cargo.toml` 的 `[dependencies]` 中添加：

```toml
keyring = { version = "3", features = ["apple-native", "windows-native", "sync-secret-service"] }
```

完整 `[dependencies]` 节变为：

```toml
[dependencies]
tauri = { version = "2", features = [] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
ureq = { version = "2.9", default-features = false }
keyring = { version = "3", features = ["apple-native", "windows-native", "sync-secret-service"] }
```

- [ ] **Step 2: 验证编译通过**

```bash
cd frontend/src-tauri && cargo check 2>&1 | tail -10
```

Expected: `Finished` 或仅 warnings，无 error

- [ ] **Step 3: Commit**

```bash
git add frontend/src-tauri/Cargo.toml frontend/src-tauri/Cargo.lock
git commit -m "chore: 添加 keyring 3.x 依赖到 Tauri"
```

---

### Task 5: lib.rs — 将三个 command 改为使用 keyring

**Files:**
- Modify: `frontend/src-tauri/src/lib.rs:185-223`

- [ ] **Step 1: 在 lib.rs 顶部添加 use 声明**

在文件顶部的 `use` 语句后添加：

```rust
use keyring::Entry;
```

- [ ] **Step 2: 用 keyring 实现 get_api_key**

将 `get_api_key` 函数（第 185-198 行）替换为：

```rust
#[tauri::command]
fn get_api_key(_app: AppHandle) -> Result<Option<String>, String> {
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
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(e) => Err(format!("读取 API Key 失败: {e}")),
    }
}
```

- [ ] **Step 3: 用 keyring 实现 set_api_key**

将 `set_api_key` 函数（第 200-214 行）替换为：

```rust
#[tauri::command]
fn set_api_key(_app: AppHandle, value: String) -> Result<(), String> {
    let trimmed = value.trim().to_string();
    if trimmed.is_empty() {
        return Err("API Key 不能为空".into());
    }
    let entry = Entry::new("pim", "api_key").map_err(|e| format!("keyring init failed: {e}"))?;
    entry.set_password(&trimmed).map_err(|e| format!("写入 API Key 失败: {e}"))
}
```

- [ ] **Step 4: 用 keyring 实现 clear_api_key**

将 `clear_api_key` 函数（第 216-223 行）替换为：

```rust
#[tauri::command]
fn clear_api_key(_app: AppHandle) -> Result<(), String> {
    let entry = Entry::new("pim", "api_key").map_err(|e| format!("keyring init failed: {e}"))?;
    match entry.delete_credential() {
        Ok(()) => Ok(()),
        Err(keyring::Error::NoEntry) => Ok(()), // 不存在时视为成功
        Err(e) => Err(format!("清除 API Key 失败: {e}")),
    }
}
```

- [ ] **Step 5: 同时移除不再需要的旧函数和 imports**

删除 `api_key_file_path` 函数（第 174-183 行）以及 `#[cfg(unix)]` 下 `use std::os::unix::fs::PermissionsExt;` 的 import（如果不再需要）。

- [ ] **Step 6: 验证编译**

```bash
cd frontend/src-tauri && cargo check 2>&1 | tail -10
```

Expected: 无 error

- [ ] **Step 7: Commit**

```bash
git add frontend/src-tauri/src/lib.rs
git commit -m "feat: Tauri API Key 存储从明文文件迁移到系统 Keychain"
```

---

### Task 6: lib.rs — 添加旧文件迁移逻辑

**Files:**
- Modify: `frontend/src-tauri/src/lib.rs`

迁移逻辑在 `get_api_key` 中：首次调用时若 Keychain 无值但旧文件存在，则读取 → 写入 Keychain → 删除文件。

- [ ] **Step 1: 在 get_api_key 中添加迁移逻辑**

将 `get_api_key` 更新为：

```rust
#[tauri::command]
fn get_api_key(app: AppHandle) -> Result<Option<String>, String> {
    let entry = Entry::new("pim", "api_key").map_err(|e| format!("keyring init failed: {e}"))?;
    match entry.get_password() {
        Ok(value) => {
            let trimmed = value.trim().to_string();
            if trimmed.is_empty() { Ok(None) } else { Ok(Some(trimmed)) }
        }
        Err(keyring::Error::NoEntry) => {
            // 尝试从旧明文文件迁移
            if let Ok(migrated) = migrate_from_legacy_file(&app, &entry) {
                return Ok(migrated);
            }
            Ok(None)
        }
        Err(e) => Err(format!("读取 API Key 失败: {e}")),
    }
}

/// 从旧的 secrets/pim_api_key 文件读取，写入 Keychain，删除文件。
/// 成功返回 Some(key)，旧文件不存在返回 Ok(None)。
fn migrate_from_legacy_file(app: &AppHandle, entry: &Entry) -> Result<Option<String>, String> {
    let base = app.path().app_config_dir()
        .map_err(|e| format!("cannot get config dir: {e}"))?;
    let legacy = base.join("secrets").join("pim_api_key");
    if !legacy.exists() {
        return Ok(None);
    }
    let raw = std::fs::read_to_string(&legacy)
        .map_err(|e| format!("read legacy key: {e}"))?;
    let trimmed = raw.trim().to_string();
    if trimmed.is_empty() {
        let _ = std::fs::remove_file(&legacy);
        return Ok(None);
    }
    entry.set_password(&trimmed).map_err(|e| format!("migrate to keyring: {e}"))?;
    let _ = std::fs::remove_file(&legacy); // 迁移成功后删除旧文件
    eprintln!("[pim-tauri] API Key 已从旧文件迁移到系统 Keychain");
    Ok(Some(trimmed))
}
```

- [ ] **Step 2: 编译验证**

```bash
cd frontend/src-tauri && cargo check 2>&1 | tail -10
```

Expected: 无 error

- [ ] **Step 3: Commit**

```bash
git add frontend/src-tauri/src/lib.rs
git commit -m "feat: Tauri 添加旧明文文件 → Keychain 自动迁移逻辑"
```

---

### Task 7: tauri.conf.json — 配置最小 CSP

**Files:**
- Modify: `frontend/src-tauri/tauri.conf.json:13-16`

- [ ] **Step 1: 更新 CSP**

将 `frontend/src-tauri/tauri.conf.json` 中的 `"security"` 节：

```json
"security": {
  "csp": null,
  "capabilities": ["default"]
}
```

改为：

```json
"security": {
  "csp": "default-src 'self'; connect-src 'self' http://127.0.0.1:8000; img-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'",
  "capabilities": ["default"]
}
```

- [ ] **Step 2: 验证 Tauri 构建配置有效**

```bash
cd frontend/src-tauri && cargo check 2>&1 | tail -5
```

- [ ] **Step 3: （可选）手工验证：以 dev 模式启动 Tauri，检查无 CSP 报错**

```bash
cd frontend && npm run tauri:dev
```

在浏览器 DevTools Console 中确认无 CSP 相关错误。

- [ ] **Step 4: Commit**

```bash
git add frontend/src-tauri/tauri.conf.json
git commit -m "chore: 配置 Tauri 最小 CSP，替换 null 策略"
```

---

### Task 8: 验证完整链路

- [ ] **Step 1: 运行后端测试确认全部通过**

```bash
cd backend && ./.venv/bin/pytest -q --no-header 2>&1 | tail -3
```

Expected: 全部通过

- [ ] **Step 2: 验证 job_id 出现在日志中**

```bash
cd backend && LOG_FORMAT=json ./.venv/bin/python -c "
from app.utils.logger import set_job_id, get_logger
set_job_id('test-job-123')
get_logger('verify').info('job id test', extra={'phase': 'fetch', 'source_id': 'src-1'})
" 2>&1
```

Expected 输出包含：
```json
{"timestamp": "...", "level": "INFO", "logger": "verify", "message": "job id test", "job_id": "test-job-123", "phase": "fetch", "source_id": "src-1"}
```

- [ ] **Step 3: Commit 最终验证**

```bash
git add -A
git commit -m "chore: Stream 4 所有任务验证完毕"
```
