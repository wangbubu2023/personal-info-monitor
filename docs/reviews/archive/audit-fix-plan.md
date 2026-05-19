# PIM 代码审计修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 验证并修复 PIM 代码审计报告（第三版）中全部 16 个问题

**Architecture:** 按优先级分三阶段推进 — 第一阶段修复严重/阻断性问题，第二阶段修复中等问题，第三阶段处理轻微问题和清理工作。每个 Task 独立可提交。

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy / APScheduler (后端), React 18 / TypeScript / Vite / Ant Design (前端)

**审计验证修正：**
- Q-1: asyncio.run() 7 处均在同步函数中，经 asyncio.to_thread() 隔离，非"在 async 函数体内误用"，降级为**中等**（架构/可维护性问题）
- T-2: 前端已有 6 个测试文件，非"完全无测试"
- SourcesPage.tsx: 8 行包装组件，非空文件，不删除
- .gitignore: 已包含 output/，仅需补充 src-tauri/target/

---

## 第一阶段：严重 + 高优先级问题

### Task 1: 修复 asyncio.run() 架构问题 [Q-1, 降级为中等]

**问题：** pipeline 和 tasks 中 7 处 `asyncio.run()` 在同步函数中使用，通过 `asyncio.to_thread()` 隔离。虽不会崩溃，但：(1) 循环中反复创建/销毁事件循环性能差，(2) 若未来有人从 async 上下文直调会出 bug，(3) 代码可维护性差。

**策略：** 将 pipeline 各 Stage 改为 async，在 `fetch_tasks.py` 的 `asyncio.to_thread()` 入口处统一用一个事件循环执行整个 pipeline，而非每个调用各自 `asyncio.run()`。

**Files:**
- Modify: `backend/app/pipeline/collector_stage.py`
- Modify: `backend/app/pipeline/ai_stage.py`
- Modify: `backend/app/pipeline/coordinator.py`
- Modify: `backend/app/pipeline/utils.py`
- Modify: `backend/app/tasks/process_tasks.py`
- Modify: `backend/app/tasks/fetch_auth_helpers.py`
- Modify: `backend/app/tasks/fetch_orchestrator.py` (调用入口)

- [ ] **Step 1: 理解当前调用链**

当前执行路径：
```
fetch_tasks.py: async def run_fetch_for_source()
  → await asyncio.to_thread(_query_and_fetch)   # 进入工作线程
    → _query_and_fetch() (sync)
      → run_fetch_pipeline() (sync)
        → CollectorStage.execute() (sync, 内含 asyncio.run())
        → NormalizerStage.execute() (sync)
        → coordinator._build_raw_content_objects() (sync, 内含 asyncio.run())
        → AIStage.execute() (sync, 内含 asyncio.run())
        → StorageStage.execute() (sync)
```

目标：将 pipeline 执行改为 async，在 `_query_and_fetch` 中用单个 `asyncio.run()` 驱动整个 async pipeline，而非在每个 stage 内部各自 `asyncio.run()`。

- [ ] **Step 2: 将 CollectorStage.execute 改为 async**

`backend/app/pipeline/collector_stage.py`:

将 `execute` 改为 `async def`，移除内部 `asyncio.run()`：

```python
@staticmethod
async def execute(source, source_type, db, creds, auth_warning):
    # ... 前面逻辑不变 ...
    for fetch_url in source_urls:
        try:
            source.url = fetch_url
            fetched = await collector.fetch(source)  # 直接 await
            if fetched:
                raw_contents.extend(fetched)
        except Exception as e:
            logger.error(f"Error fetching from URL {fetch_url}: {e}")
            continue
    # ... 后续不变 ...
```

- [ ] **Step 3: 将 coordinator._build_raw_content_objects 改为 async**

`backend/app/pipeline/coordinator.py`:

```python
async def _build_raw_content_objects(raw_contents, source):
    # ...
    if html and not main_text:
        main_text = await extractor.extract(html, raw.get("url"))  # 直接 await
    # ...
```

- [ ] **Step 4: 将 AIStage.execute 改为 async**

`backend/app/pipeline/ai_stage.py`:

```python
@staticmethod
async def execute(source, raw_contents, keywords):
    processor = ContentProcessor()
    processed_contents = []
    for raw_content in raw_contents:
        try:
            content = await processor.process(raw_content, source, keywords)  # 直接 await
            processed_contents.append(content)
        except Exception as e:
            logger.error(...)
            continue
    return processed_contents
```

- [ ] **Step 5: 将 utils.resolve_website_publish_time 改为 async**

`backend/app/pipeline/utils.py`:

```python
async def resolve_website_publish_time(raw_content):
    # ...
    resolved = await fetch_publish_time_from_url(url)  # 直接 await
    # ...
```

注意：`normalize_publish_time` 也需相应改为 async，因为它调用了 `resolve_website_publish_time`。

- [ ] **Step 6: 将 run_fetch_pipeline 改为 async**

修改 pipeline 入口函数（在 `collector_stage.py` 或 `fetch_orchestrator.py` 中）为 `async def`，用 `await` 串联各 stage。

- [ ] **Step 7: 在 fetch_tasks._query_and_fetch 中用单个 asyncio.run()**

`backend/app/tasks/fetch_tasks.py`:

```python
def _query_and_fetch(source_id):
    # ... DB 查询（同步）...
    result = asyncio.run(run_fetch_pipeline(source, db))  # 单个入口
    # ...
```

- [ ] **Step 8: 修复 process_tasks.py 中的 asyncio.run()**

`backend/app/tasks/process_tasks.py`:

方案 A（推荐）：将 `_process_new_content_sync` 中的异步调用提取为独立 async 函数，在 `process_new_content` 中直接 await：

```python
async def process_new_content(content_id, session_factory=None):
    # 直接 await 而非 to_thread + asyncio.run
    await _process_new_content_async(content_id)
```

方案 B：保持 to_thread 隔离，但确保每个 sync 函数只有一个 `asyncio.run()` 入口。

- [ ] **Step 9: 修复 fetch_auth_helpers.py 中的 asyncio.run()**

`backend/app/tasks/fetch_auth_helpers.py` 第 289、314 行：

将 `maybe_refresh_auth_cookies` 改为 `async def`，在调用处 `await`：

```python
async def maybe_refresh_auth_cookies(db, source, creds):
    # ...
    cookies_valid = bool(await cookies_appear_valid(source.url, cookies))
    # ...
    cookie_dict = await _login_and_capture_cookies(...)
    # ...
```

相应修改所有调用方。

- [ ] **Step 10: 运行全部后端测试验证无回归**

```bash
cd backend && python -m pytest tests/ -v --tb=short 2>&1 | head -80
```

- [ ] **Step 11: 提交**

```bash
git add backend/app/pipeline/ backend/app/tasks/process_tasks.py backend/app/tasks/fetch_auth_helpers.py
git commit -m "refactor: unify async pipeline, remove scattered asyncio.run() calls"
```

---

### Task 2: 补全 SSRF 防护 [S-1, 严重]

**问题：** `probe_service.py` 有完善的 `_assert_public_http_target()` 实现（检查 localhost、私有 IP、DNS 解析），但所有 collector 的 fetch 路径均未调用。

**策略：** 将 SSRF 检查提取为公共工具函数，在所有 collector 的 fetch 入口调用。

**Files:**
- Create: `backend/app/utils/ssrf.py`
- Modify: `backend/app/collectors/base.py`
- Modify: `backend/app/collectors/website.py`
- Modify: `backend/app/collectors/rss.py`
- Modify: `backend/app/collectors/youtube.py`
- Modify: `backend/app/collectors/podcast.py`
- Modify: `backend/app/collectors/x_twitter_feed.py`
- Test: `backend/tests/test_ssrf_protection.py`

- [ ] **Step 1: 提取 SSRF 检查为独立工具函数**

从 `probe_service.py` 中提取 `_assert_public_http_target` 和 `_is_private_address`、`_resolve_host_addresses` 为独立模块 `backend/app/utils/ssrf.py`：

```python
"""SSRF protection utilities.

Extracted from ProbeService to be reusable across all HTTP-fetching code paths.
"""
import ipaddress
import socket
from urllib.parse import urlparse
from typing import List

import logging

logger = logging.getLogger(__name__)


def _is_private_address(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
    except ValueError:
        return False


async def _resolve_host_addresses(hostname: str, port: int) -> List[str]:
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        infos = await loop.getaddrinfo(hostname, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
        return list({info[4][0] for info in infos})
    except socket.gaierror:
        return []


async def assert_public_http_target(url: str) -> None:
    """Raise ValueError if *url* points to a private/internal network target."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"unsupported scheme: {parsed.scheme or 'missing'}")

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("missing hostname")
    if hostname == "localhost":
        raise ValueError("localhost is not allowed")
    if _is_private_address(hostname):
        raise ValueError(f"private address is not allowed: {hostname}")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = await _resolve_host_addresses(hostname, port)
    if not addresses:
        raise ValueError("hostname did not resolve")

    blocked = sorted(ip for ip in addresses if _is_private_address(ip))
    if blocked:
        raise ValueError(f"resolved to private address: {', '.join(blocked)}")
```

- [ ] **Step 2: 在 base collector 中添加 SSRF 检查钩子**

`backend/app/collectors/base.py` — 在 `BaseCollector` 中添加：

```python
from app.utils.ssrf import assert_public_http_target

class BaseCollector:
    async def _check_ssrf(self, url: str) -> None:
        """Check URL against SSRF before fetching. Subclasses can override to skip."""
        await assert_public_http_target(url)
```

- [ ] **Step 3: 在 website.py fetch 入口添加 SSRF 检查**

`backend/app/collectors/website.py` — 在 `fetch()` 方法开头：

```python
async def fetch(self, source):
    await self._check_ssrf(source.url)
    # ... 原有逻辑 ...
```

同样在 `_fetch_article_html` 中对 `article_url` 做检查。

- [ ] **Step 4: 在 rss.py fetch 入口添加 SSRF 检查**

- [ ] **Step 5: 在 youtube.py fetch 入口添加 SSRF 检查**

YouTube URL 可跳过（固定域名 youtube.com/youtu.be），但仍建议做基本校验。

- [ ] **Step 6: 在 podcast.py fetch 入口添加 SSRF 检查**

- [ ] **Step 7: 在 x_twitter_feed.py _http_get 入口添加 SSRF 检查**

- [ ] **Step 8: 让 ProbeService 复用新的 ssrf.py**

修改 `probe_service.py`，将其 `_assert_public_http_target` 改为调用 `ssrf.assert_public_http_target`，避免代码重复。

- [ ] **Step 9: 编写 SSRF 防护测试**

`backend/tests/test_ssrf_protection.py`:

```python
import pytest
from app.utils.ssrf import assert_public_http_target

@pytest.mark.asyncio
async def test_rejects_localhost():
    with pytest.raises(ValueError, match="localhost"):
        await assert_public_http_target("http://localhost/admin")

@pytest.mark.asyncio
async def test_rejects_private_ip():
    with pytest.raises(ValueError, match="private"):
        await assert_public_http_target("http://192.168.1.1/admin")

@pytest.mark.asyncio
async def test_rejects_loopback():
    with pytest.raises(ValueError, match="private"):
        await assert_public_http_target("http://127.0.0.1:8080/secret")

@pytest.mark.asyncio
async def test_allows_public_url():
    # Should not raise for a public URL
    await assert_public_http_target("https://example.com")

@pytest.mark.asyncio
async def test_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="unsupported scheme"):
        await assert_public_http_target("ftp://example.com/file")
```

- [ ] **Step 10: 运行测试**

```bash
cd backend && python -m pytest tests/test_ssrf_protection.py -v
```

- [ ] **Step 11: 提交**

```bash
git add backend/app/utils/ssrf.py backend/app/collectors/ backend/app/services/probe_service.py backend/tests/test_ssrf_protection.py
git commit -m "security: add SSRF protection to all collector fetch paths"
```

---

### Task 3: 配置日志轮转 + 清理 Celery 遗留 [O-1, O-2, D-1]

**问题：**
- 日志仅输出到 stdout，无文件轮转（`.pim-local-logs/` 已达 109MB）
- 6 个 Celery 日志文件 + 3 个 PID 文件为旧架构遗留

**Files:**
- Modify: `backend/app/utils/logger.py`
- Modify: `pim` (运维脚本)
- Modify: `.gitignore`

- [ ] **Step 1: 在 logger.py 中添加 RotatingFileHandler**

`backend/app/utils/logger.py` — 在 `setup_logging()` 中，除 StreamHandler 外增加文件 handler：

```python
from logging.handlers import RotatingFileHandler
import os

def setup_logging(level="INFO", log_format="json"):
    # ... 现有 StreamHandler 逻辑 ...

    # File handler with rotation
    log_dir = os.environ.get("PIM_LOG_DIR", ".pim-local-logs")
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "backend.log"),
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.addFilter(_RequestContextFilter())
        file_handler.setFormatter(_JsonFormatter())
        root_logger.addHandler(file_handler)
```

- [ ] **Step 2: 在 pim 脚本中添加清理 Celery 遗留的命令**

在 `pim` 脚本的 `setup` 或新增 `cleanup` 子命令中：

```bash
cleanup_celery_remnants() {
    echo "Cleaning Celery remnants..."
    rm -f .pim-local-logs/celery_* .pim-local-logs/celery-*
    rm -f .pim-local-pids/celery_*
    echo "Done."
}
```

- [ ] **Step 3: 手动清理当前 Celery 遗留文件**

```bash
rm -f .pim-local-logs/celery_* .pim-local-logs/celery-*
rm -f .pim-local-pids/celery_*
```

- [ ] **Step 4: 补充 .gitignore**

追加：
```gitignore
# Tauri build artifacts
frontend/src-tauri/target/

# Runtime PID files
.pim-local-pids/
```

- [ ] **Step 5: 提交**

```bash
git add backend/app/utils/logger.py pim .gitignore
git commit -m "ops: add log rotation, clean Celery remnants, update .gitignore"
```

---

## 第二阶段：中等优先级问题

### Task 4: URL 格式校验改用 HttpUrl [S-3]

**Files:**
- Modify: `backend/app/schemas/source.py`
- Test: 运行现有 `test_api_sources.py`

- [ ] **Step 1: 将 url 字段改为 Pydantic HttpUrl**

`backend/app/schemas/source.py`:

```python
from pydantic import HttpUrl

class SourceBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., pattern="^(website|rss|x|youtube|podcast)$")
    url: HttpUrl = Field(...)
    extra_urls: List[HttpUrl] = Field(default_factory=list)
```

注意：Pydantic v2 的 `HttpUrl` 返回 `Url` 对象而非 `str`，需确认下游代码兼容（可能需要 `str(source.url)` 或自定义 validator 返回 str）。若 ORM 层需要 str，用 `@field_validator` 将 `HttpUrl` 转回 `str`：

```python
from pydantic import field_validator

class SourceBase(BaseModel):
    url: str = Field(..., min_length=1)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        from pydantic import HttpUrl
        HttpUrl(v)  # raises if invalid
        return v
```

- [ ] **Step 2: 对 SourceUpdate 做同样处理**

- [ ] **Step 3: 运行测试验证**

```bash
cd backend && python -m pytest tests/test_api_sources.py -v
```

- [ ] **Step 4: 提交**

```bash
git add backend/app/schemas/source.py
git commit -m "security: validate source URLs with HttpUrl format"
```

---

### Task 5: 消除前端 TypeScript `as any` [Q-4]

**问题：** `AIModelTab.tsx` 中 10 处 `(settings as any)`，`ReaderPage.tsx` 中 1 处。

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/components/Settings/AIModelTab.tsx`
- Modify: `frontend/src/pages/ReaderPage.tsx`

- [ ] **Step 1: 阅读 AIModelTab.tsx 找出所有 as any 访问的字段**

需要确定 `settings` 对象上缺少哪些类型字段（translation_model、summary_model 等）。

- [ ] **Step 2: 在 types/index.ts 中补充完整类型定义**

根据后端 `schemas/config.py` 和实际 API 响应，为 Settings 类型添加缺少的字段：

```typescript
export interface AIModelConfig {
  provider: string;
  model: string;
}

export interface PIMSettings {
  // ... 现有字段 ...
  translation_model?: AIModelConfig;
  summary_model?: AIModelConfig;
  keyword_model?: AIModelConfig;
  // ... 其他缺少的字段 ...
}
```

- [ ] **Step 3: 修改 AIModelTab.tsx 移除所有 as any**

将 `(settings as any).translation_model?.provider` 替换为类型安全的访问。

- [ ] **Step 4: 修改 ReaderPage.tsx 移除 as any**

- [ ] **Step 5: 运行 TypeScript 类型检查**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

- [ ] **Step 6: 提交**

```bash
git add frontend/src/types/index.ts frontend/src/components/Settings/AIModelTab.tsx frontend/src/pages/ReaderPage.tsx
git commit -m "fix: replace TypeScript 'as any' with proper type definitions"
```

---

### Task 6: 修复静默异常吞没 [Q-5]

**问题：** 15+ 处 `except Exception` 后无日志直接 `continue`/`return None`/`return {}`。

**已确认位置：**
- `probe_service.py`: 行 257, 314, 600, 730
- `base.py`: 行 91
- `translator.py`: 行 26, 37, 66（return {} / return False）

**Files:**
- Modify: `backend/app/services/probe_service.py`
- Modify: `backend/app/collectors/base.py`
- Modify: `backend/app/processors/translator.py`

- [ ] **Step 1: 修复 probe_service.py 中 4 处静默异常**

为每处添加 `logger.debug()` 或 `logger.warning()`，包含上下文信息：

```python
# 行 257-258: common RSS 路径探测失败
except Exception as exc:
    logger.debug("RSS path probe failed for %s: %s", url, exc)
    continue

# 行 314-315: BeautifulSoup select 失败
except Exception as exc:
    logger.debug("BS4 select failed for %s: %s", selector, exc)
    continue

# 行 600-601: YouTube playlist ID 提取失败
except Exception as exc:
    logger.debug("Failed to extract YouTube playlist ID from %s: %s", url, exc)
    return None

# 行 730-731: HTTP GET 失败
except Exception as exc:
    logger.warning("HTTP GET failed for %s: %s", url, exc)
    return None
```

- [ ] **Step 2: 修复 base.py 行 91**

```python
except Exception as exc:
    logger.debug("Failed to parse datetime %r: %s", value, exc)
    return None
```

- [ ] **Step 3: 修复 translator.py 行 26, 37, 66**

```python
# 行 26-27
except Exception as exc:
    logger.warning("Translation config parsing failed: %s", exc)
    return {}

# 行 37-38
except Exception as exc:
    logger.debug("Translation availability check failed: %s", exc)
    return False

# 行 66-72
except Exception as exc:
    logger.warning("Translation config fallback failed: %s", exc)
    return {默认值}
```

- [ ] **Step 4: 全局搜索其他静默异常**

```bash
cd backend && rg "except Exception.*:" --no-filename -A1 app/ | rg -B1 "(continue|return None|return \{\}|return False)" | head -40
```

修复发现的其他位置。

- [ ] **Step 5: 运行测试**

```bash
cd backend && python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

- [ ] **Step 6: 提交**

```bash
git add backend/app/
git commit -m "fix: add logging to silently swallowed exceptions"
```

---

### Task 7: 内容截断添加日志 [P-1]

**问题：** 5 处 `[:50000]` 硬截断无任何日志提示。

**Files:**
- Modify: `backend/app/pipeline/coordinator.py`
- Modify: `backend/app/tasks/process_tasks.py`
- Modify: `backend/app/processors/content_processor.py`
- Modify: `backend/app/pipeline/dedupe.py`
- Modify: `backend/app/api/contents_reader.py`

- [ ] **Step 1: 提取公共截断函数**

`backend/app/utils/text.py`（如已存在则在其中添加）:

```python
MAX_FULL_CONTENT_LENGTH = 50_000

def truncate_content(text: str, url: str = "") -> str:
    if text and len(text) > MAX_FULL_CONTENT_LENGTH:
        logger.warning(
            "Content truncated from %d to %d chars: %s",
            len(text), MAX_FULL_CONTENT_LENGTH, url[:100],
        )
        return text[:MAX_FULL_CONTENT_LENGTH]
    return text
```

- [ ] **Step 2: 替换所有 [:50000] 为 truncate_content() 调用**

逐一替换 5 处硬编码截断。

- [ ] **Step 3: 运行测试**

- [ ] **Step 4: 提交**

```bash
git add backend/app/utils/text.py backend/app/pipeline/ backend/app/tasks/ backend/app/processors/ backend/app/api/
git commit -m "fix: log content truncation with original length context"
```

---

### Task 8: TaskTracker 改为 context manager [P-2]

**问题：** `start_fetch()`/`end_fetch()` 成对调用，异常时可能不匹配。

**Files:**
- Modify: `backend/app/background.py`
- Modify: 所有调用 `start_fetch`/`end_fetch`/`start_process`/`end_process` 的文件

- [ ] **Step 1: 添加 context manager 方法**

`backend/app/background.py`:

```python
from contextlib import asynccontextmanager

class TaskTracker:
    # ... 保留现有方法 ...

    @asynccontextmanager
    async def track_fetch(self):
        await self.start_fetch()
        try:
            yield
        finally:
            await self.end_fetch()

    @asynccontextmanager
    async def track_process(self):
        await self.start_process()
        try:
            yield
        finally:
            await self.end_process()
```

- [ ] **Step 2: 将所有调用方改为 context manager 用法**

```python
# Before:
await tracker.start_fetch()
try:
    result = await do_fetch()
finally:
    await tracker.end_fetch()

# After:
async with tracker.track_fetch():
    result = await do_fetch()
```

- [ ] **Step 3: 运行测试**

- [ ] **Step 4: 提交**

```bash
git add backend/app/background.py backend/app/tasks/
git commit -m "refactor: use context manager for TaskTracker to prevent counter mismatch"
```

---

### Task 9: 移除错误响应中的系统信息 [S-4]

**Files:**
- Modify: `backend/app/api/sources.py`

- [ ] **Step 1: 修改 409 错误响应**

`backend/app/api/sources.py` 行 85-92:

```python
# Before:
detail=(
    f"监控源数量已达到上限（{max_sources}）。"
    f"当前 {current_total}，最多还能新增 {remaining}。"
)

# After:
logger.warning(
    "Source limit reached: current=%d, max=%d, attempted_add=%d",
    current_total, max_sources, len(new_sources),
)
detail="监控源数量已达到上限，无法添加更多。"
```

- [ ] **Step 2: 运行 sources API 测试**

```bash
cd backend && python -m pytest tests/test_api_sources.py -v
```

- [ ] **Step 3: 提交**

```bash
git add backend/app/api/sources.py
git commit -m "security: remove internal quota details from error response"
```

---

### Task 10: 删除未使用的 zustand 依赖 [精简]

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: 确认 zustand 未被使用**

```bash
cd frontend && rg "zustand" src/
```

应无结果。

- [ ] **Step 2: 卸载 zustand**

```bash
cd frontend && npm uninstall zustand
```

- [ ] **Step 3: 提交**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "chore: remove unused zustand dependency"
```

---

## 第三阶段：轻微问题 + 长期改进

### Task 11: 拆分 website.py + 减少深层嵌套 [A-1, Q-2, Q-3]

**问题：** `website.py` 818 行，混合了 HTTP 抓取、Playwright 浏览、HTML 解析、Cookie 管理。`_fetch_article_html` 区域有 5 层嵌套和重复模式。

**Files:**
- Modify: `backend/app/collectors/website.py`
- Create: `backend/app/collectors/website_fetcher.py` (HTTP/Playwright 获取)
- Create: `backend/app/collectors/website_parser.py` (HTML 解析与内容提取)

- [ ] **Step 1: 分析 website.py 的职责边界**

阅读全文，将方法按职责分组：
- HTTP 获取相关方法 → `website_fetcher.py`
- HTML 解析/提取相关方法 → `website_parser.py`
- 主 `WebsiteCollector` 类保留在 `website.py`，组合使用上述两个模块

- [ ] **Step 2: 提取 `_try_playwright_fetch` 公共方法**

消除 `_fetch_article_html` 中重复 3 次的 Playwright 回退模式：

```python
async def _try_playwright_fetch(self, url, cookies, source_url, browser_session):
    if not (cookies or self._has_browser_session(browser_session or {})):
        return None
    html, final_url, reason = await self._fetch_article_html_with_playwright(
        url, cookies, source_url, browser_session=browser_session
    )
    return (html, final_url, None) if html else None
```

- [ ] **Step 3: 用 early return 重写 _fetch_article_html**

减少嵌套层级至最多 3 层。

- [ ] **Step 4: 创建 website_fetcher.py**

- [ ] **Step 5: 创建 website_parser.py**

- [ ] **Step 6: 重构 website.py 组合新模块**

- [ ] **Step 7: 运行测试**

- [ ] **Step 8: 提交**

```bash
git add backend/app/collectors/website*.py
git commit -m "refactor: split website.py into fetcher/parser, reduce nesting"
```

---

### Task 12: 替换 window.prompt 为安全输入模态框 [S-5]

**Files:**
- Modify: `frontend/src/services/api.ts`
- Create or Modify: `frontend/src/components/ui/ApiKeyModal.tsx`

- [ ] **Step 1: 创建 API Key 输入模态框组件**

使用 Ant Design Modal + Input.Password：

```tsx
import { Modal, Input } from 'antd';

export function promptApiKey(): Promise<string | null> {
  return new Promise((resolve) => {
    let value = '';
    Modal.confirm({
      title: '请输入 PIM API Key',
      content: (
        <Input.Password
          onChange={(e) => { value = e.target.value; }}
          placeholder="API Key"
          autoFocus
        />
      ),
      onOk: () => resolve(value.trim() || null),
      onCancel: () => resolve(null),
    });
  });
}
```

- [ ] **Step 2: 替换 api.ts 中的 window.prompt**

- [ ] **Step 3: 验证功能**

- [ ] **Step 4: 提交**

```bash
git add frontend/src/
git commit -m "security: replace window.prompt with secure modal for API key input"
```

---

### Task 13: 清理磁盘 + Tauri 构建缓存 [精简]

- [ ] **Step 1: 清理 Tauri 构建缓存**

```bash
rm -rf frontend/src-tauri/target/
```

- [ ] **Step 2: 清理 __pycache__**

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
```

- [ ] **Step 3: 清理播客封面缓存**

```bash
rm -rf output/podcast_covers/
```

- [ ] **Step 4: 确认 .gitignore 已更新（Task 3 中完成）**

---

### Task 14: 补充前端架构文档 [D-2]

**Files:**
- Create: `frontend/README.md`

- [ ] **Step 1: 编写前端架构说明**

包含：
- 技术栈（React 18 + Vite + Ant Design + TypeScript + React Query）
- 目录结构说明
- 状态管理策略（React Query 管理服务端状态 + localStorage + Tauri IPC）
- 组件分层（pages → components → services → types）
- 构建与开发命令

- [ ] **Step 2: 提交**

```bash
git add frontend/README.md
git commit -m "docs: add frontend architecture documentation"
```

---

### Task 15: 提升后端测试覆盖率 [T-1]

**当前覆盖率：27.95%，目标：50%+**

**优先补测的模块（按风险排序）：**
1. `collectors/` — 核心采集逻辑
2. `pipeline/` — 数据处理管道
3. `auth.py` — 认证（当前 46.15%）
4. `background.py` — 任务追踪（当前 38.38%）

**Files:**
- Create: `backend/tests/test_pipeline_coordinator.py`
- Create: `backend/tests/test_pipeline_stages.py`
- Create: `backend/tests/test_collectors_website.py`
- Create: `backend/tests/test_auth.py` (补充)
- Create: `backend/tests/test_background.py`

- [ ] **Step 1: 为 pipeline coordinator 编写单元测试**

测试 `_build_raw_content_objects` 的各种输入：正常、空内容、HTML 内容、超长内容截断。

- [ ] **Step 2: 为 pipeline stages 编写单元测试**

Mock collector/processor，测试 stage 执行流程、错误处理。

- [ ] **Step 3: 为 website collector 编写单元测试**

Mock aiohttp/Playwright，测试 fetch、SSRF 检查、Google News 处理。

- [ ] **Step 4: 补充 auth.py 测试**

测试 API Key 验证、错误 key、缺失 key。

- [ ] **Step 5: 为 TaskTracker 编写测试**

测试 context manager、异常时自动释放、并发安全。

- [ ] **Step 6: 运行覆盖率报告**

```bash
cd backend && python -m pytest tests/ --cov=app --cov-report=term-missing 2>&1 | tail -40
```

- [ ] **Step 7: 提交**

```bash
git add backend/tests/
git commit -m "test: add unit tests for pipeline, collectors, auth, and background"
```

---

## 执行顺序与依赖关系

```
Task 1 (asyncio) ──┐
Task 2 (SSRF)  ────┤── 可并行，但建议 Task 1 先完成（pipeline 改 async 后 SSRF 检查直接用 await）
Task 3 (日志+清理) ─┘── 独立，可并行

Task 4 (URL校验) ──── 独立
Task 5 (TypeScript) ── 独立
Task 6 (静默异常) ──── 独立
Task 7 (截断日志) ──── 独立
Task 8 (TaskTracker) ─ 独立
Task 9 (错误响应) ──── 独立
Task 10 (zustand) ──── 独立

Task 11 (拆分website) ─ 依赖 Task 1 (async 改造) + Task 2 (SSRF)
Task 12 (API Key模态框) ── 独立
Task 13 (磁盘清理) ────── 依赖 Task 3 (.gitignore)
Task 14 (前端文档) ────── 独立
Task 15 (测试覆盖) ────── 依赖 Task 1-2（测试改造后的代码）
```

---

## 不处理的项目（经验证不属实或优先级极低）

| 审计项 | 原因 |
|--------|------|
| 删除 SourcesPage.tsx | 经验证为 8 行包装组件，非空文件，保留 |
| 前端"完全无测试" | 经验证已有 6 个测试文件，仅需补充而非从零开始 |
| .gitignore 补 output/ | 经验证已包含 |
| A-2 X/Twitter 采集器整合 | 轻微，当前拆分有合理性，暂不处理 |
| A-3 configs 路由整合 | 轻微，当前按功能域拆分合理，暂不处理 |
| Web 版 HttpOnly Cookie | 大改动，需单独设计，不在本次范围 |
