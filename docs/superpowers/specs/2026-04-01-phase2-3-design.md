# PIM 二、三阶段重构设计文档

**日期**：2026-04-01  
**来源**：代码审计报告第二、三阶段改进路线图  
**执行策略**：四个并行流，独立开工，按顺序合并（Frontend → Backend → CI/Docs → Tauri/Observability）

---

## 整体架构

| 流 | 范围 | 依赖 |
|----|------|------|
| Stream 1：Frontend | SourceManager 重构 | 无 |
| Stream 2：Backend | sources/probe 拆分 + 有界队列 + 补测 | 无 |
| Stream 3：CI + Docs | GitHub Actions + ADR + 贡献指南 | 无 |
| Stream 4：Tauri + Observability | Keychain + CSP + job_id 链路追踪 | 无 |

---

## Stream 1：Frontend — SourceManager 重构

### 目标
将 1299 行的 `SourceManager.tsx` 按"逻辑下沉 + 视图拆分"策略重构，提升可维护性，同时消除与 `APIKeysTab.tsx` 的重复辅助函数。

### 文件结构

```
frontend/src/
├── utils/
│   └── sourceAuth.ts                     # 新建：从 SourceManager 提取共享工具函数
│                                         #   normalizeHost, resolveSiteUrlForAuth,
│                                         #   isXCookieProfile, getAuthConfigDisplayName,
│                                         #   getDefaultSharedXAuthConfigId
└── components/SourceList/
    ├── SourceManager.tsx                  # 改为薄壳：只渲染 <SourceListContainer />
    ├── SourceListContainer.tsx            # 新建：列表容器，组合三个 hook，渲染 tabs/表格/批量操作
    ├── SourceEditorModal.tsx              # 新建：新增/编辑 Modal
    │                                     #   Props: { open, source, authConfigs, categories, onSave, onClose }
    ├── SourceImportModal.tsx              # 新建：批量导入 Modal（独立管理导入状态）
    ├── hooks/
    │   ├── useSourceList.ts               # 新建：分页、筛选、搜索防抖、tab 计数、行批量选择
    │   ├── useSourceEditor.ts             # 新建：form 状态、create/update/delete mutations、认证字段推导
    │   └── useSourceImport.ts             # 新建：文件解析、预览状态、批量创建 mutation
    ├── FetchStatusIcon.tsx                # 不动
    └── importUtils.ts                     # 不动
```

### 数据流
1. `SourceManager` → 渲染 `<SourceListContainer />`
2. `SourceListContainer` 调用 `useSourceList`、`useSourceEditor`、`useSourceImport`，将回调以 props 传给 Modal 组件
3. `SourceEditorModal` / `SourceImportModal` 不持有业务逻辑，只渲染表单并触发回调
4. `sourceAuth.ts` 同时供 `APIKeysTab.tsx` 引用，消除重复实现

### 行为约束
- 对外接口不变：`Settings.tsx` 仍 `import SourceManager` 无需修改
- 现有测试（`Settings.test.tsx`）继续通过，无需修改

---

## Stream 2：Backend — sources/probe 拆分 + 有界队列 + 补测

### 子项目 A：sources.py 拆分

**现状**：`backend/app/api/sources.py` 730 行，混合查询、变更、探测、批量导入四类路由。

```
backend/app/api/
├── sources/
│   ├── __init__.py          # 组合所有子路由；对外 router 接口不变
│   ├── _helpers.py          # 私有工具：serialize_source, _ensure_quota, _normalize_extra_urls,
│   │                        #   _source_type_value, _ensure_supported_source_type,
│   │                        #   _exclude_disabled_source_types, _source_is_visible,
│   │                        #   _invalidate_source_cache, _coerce_limit_int,
│   │                        #   _resolve_max_sources_limit, _get_source_urls,
│   │                        #   _pick_best_probe, _find_matching_auth_config_id,
│   │                        #   _probe_urls, _compute_fetch_status
│   ├── query.py             # list_sources, get_source, export_sources
│   ├── mutation.py          # create_source, update_source, delete_source
│   ├── probe.py             # probe_url, probe_source, probe_all_sources
│   └── fetch_import.py      # trigger_fetch, trigger_fetch_all, bulk_import
└── sources.py               # 删除
```

### 子项目 B：probe_service.py 拆分

**现状**：`backend/app/services/probe_service.py` 707 行，`ProbeService` 类内含四种类型的探测逻辑。

```
backend/app/services/
├── probe_service.py              # 保留：ProbeService 基类 + probe() 调度方法 + 公共 helpers
│                                 #   (_is_private_address, _assert_public_http_target)
└── probe_strategies/
    ├── __init__.py
    ├── rss.py                    # _probe_rss, _discover_rss, _try_common_rss_paths,
    │                             #   _test_rss_feed, _check_known_feeds
    ├── website.py                # _probe_website, _test_scrape
    ├── x.py                      # _probe_x, _extract_x_username
    └── youtube.py                # _probe_youtube, _extract_youtube_channel_id,
                                  #   _resolve_youtube_channel_id_from_page,
                                  #   _resolve_youtube_channel_id_from_search,
                                  #   _normalize_youtube_channel_page_url,
                                  #   _youtube_channel_page_candidates
```

`ProbeService` 通过 mixin 或委托方式调用各策略文件，对外接口（`probe(url, source_type)`）不变。

### 子项目 C：有界任务队列

**现状**：4 处 `asyncio.create_task(...)` 直接向事件循环堆积任务，无背压保护。

**方案**：引入 `asyncio.Queue(maxsize=N)` + worker 协程，纯标准库，无外部依赖。

```
backend/app/tasks/
└── task_queue.py
```

**接口设计**：
```python
class BoundedTaskQueue:
    def __init__(self, fetch_maxsize: int = 200, process_maxsize: int = 200): ...
    async def enqueue_fetch(self, source_id: str, manual_trigger: bool = False) -> bool:
        """入队抓取任务。队列满时返回 False（丢弃并记录日志），不阻塞调用方。"""
    async def enqueue_process(self, content_id: str) -> bool:
        """入队处理任务。队列满时返回 False。"""
    async def start_workers(self, fetch_workers: int = 4, process_workers: int = 4): ...
    async def stop_workers(self): ...

# 模块级单例
task_queue = BoundedTaskQueue()
```

**集成**：
- `app/main.py` lifespan：`await task_queue.start_workers()` / `await task_queue.stop_workers()`
- `fetch_tasks.py` 中的 `asyncio.create_task(fetch_source(...))` → `await task_queue.enqueue_fetch(...)`
- `fetch_tasks.py` 中的 `asyncio.create_task(process_new_content(...))` → `await task_queue.enqueue_process(...)`
- `process_tasks.py` 中的 `asyncio.create_task(...)` → `await task_queue.enqueue_process(...)`

### 子项目 D：补测（目标覆盖率 70%+）

| 文件 | 当前覆盖率 | 目标 | 新测试文件 |
|------|-----------|------|-----------|
| `app/api/sources.py` | 17% | 70% | `tests/test_api_sources_extended.py` |
| `app/tasks/fetch_tasks.py` | 15% | 70% | `tests/test_fetch_tasks_extended.py` |
| `app/tasks/process_tasks.py` | 11% | 70% | `tests/test_process_tasks_extended.py` |
| `app/api/configs_api_auth.py` | 23% | 70% | `tests/test_configs_api_auth_extended.py` |

每个测试文件覆盖：正常路径（CRUD、调度成功）+ 主要错误路径（网络失败、DB 异常、认证失败、配额超限）。

---

## Stream 3：CI + 文档

### GitHub Actions（`.github/workflows/ci.yml`）

触发条件：`push` 和 `pull_request` 到 `main`/`master`。

三个并行 job：

**backend**
```
python 3.14
pip install -e ".[dev]" 或 uv sync
pytest -q --cov=app --cov-fail-under=60
```

**frontend**
```
node 25
npm ci
npm run lint
npm test
npm audit --omit=dev
```

**security**
```
python 3.14
pip install pip-audit
pip-audit（后端依赖扫描）
```

任一 job 失败则 PR 不可合并。

### ADR 文档

- `docs/ADR-002-digest-time-field.md`：记录"统一以 fetched_at 为 Digest 时间字段"的决策、原因（抓取时间可控、避免 publish_time 为空/未来时间的问题）及替代方案。
- `docs/ADR-003-auth-credentials.md`：记录凭据存储策略演进路径——当前（文件/localStorage）→ 近期（Tauri Keychain）→ 远期（多用户场景下的令牌体系）。
- `docs/ADR-004-feature-flags.md`：记录"后端为单一事实源，前端启动时通过 `/api/config/features` 读取"的目标状态，以及当前双份维护的过渡期策略。

### 贡献指南（`docs/CONTRIBUTING.md`）

涵盖：
1. 本地环境准备（Python、Node 版本要求）
2. 测试矩阵（`pytest -q`、`npm test`、`npm run lint`、`npm audit --omit=dev`）
3. 提交前检查项
4. 分支命名约定（`feat/`、`fix/`、`chore/`）
5. PR 描述模板

---

## Stream 4：Tauri + 可观测性

### 子项目 A：Tauri Keychain + CSP

**Keychain 迁移**

当前：API Key 存为明文文件 `$APP_CONFIG/secrets/pim_api_key`（权限 0o600）。  
目标：使用系统原生凭据存储（macOS Keychain / Windows Credential Manager / Linux libsecret）。

```
frontend/src-tauri/
├── Cargo.toml    # 新增：keyring = "3"
└── src/lib.rs    # get/set/clear_api_key 改为 keyring::Entry::new("pim", "api_key")
                  # 迁移逻辑（首次启动）：
                  #   若旧文件存在 → 读取 → 写入 Keychain → 删除文件
```

三个 Tauri command 签名不变，TypeScript 层无需修改。

**CSP 配置**

```json
// frontend/src-tauri/tauri.conf.json
"security": {
  "csp": "default-src 'self'; connect-src 'self' http://127.0.0.1:8000; img-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'"
}
```

### 子项目 B：后台任务 job_id 链路追踪

不引入 OpenTelemetry，在现有 JSON 日志中注入 `job_id`。

**实现**：
- `app/utils/logger.py`：新增 `set_job_id(job_id: str)` / `clear_job_id()` / `get_job_id() -> str | None`，与现有 `set_request_id` 风格一致，使用 `contextvars.ContextVar`
- 日志格式新增字段：`job_id`、`phase`（fetch / process / digest / email）、`source_id`

**注入点**：
```python
# fetch_tasks.py — fetch_source() 入口
job_id = uuid4().hex
set_job_id(job_id)
logger.info("fetch started", extra={"phase": "fetch", "source_id": source_id, "job_id": job_id})
# ... fetch 完成后
clear_job_id()

# process_tasks.py — process_new_content() 入口
# job_id 通过 enqueue_process(content_id, job_id=job_id) 传递，在处理任务中继续使用
```

**效果**：`grep "job_id=abc123"` 即可还原从抓取到处理的完整链路，无需外部追踪系统。

---

## 合并顺序

1. Stream 1（Frontend）→ 合并，运行 `npm test` 验证
2. Stream 2（Backend）→ 合并，运行 `pytest -q` 验证
3. Stream 3（CI/Docs）→ 合并，触发首次 CI 运行验证
4. Stream 4（Tauri/Observability）→ 合并，手动测试 Tauri 构建

---

## 不在本次范围内

- OpenTelemetry 集成（三阶段"长期"项）
- Prometheus 持久化 metrics
- VPS 多用户授权体系
- 前端覆盖率门禁（可作为 CI job 的后续迭代）
