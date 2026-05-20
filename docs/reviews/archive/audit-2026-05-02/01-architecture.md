# 模块一：架构与分层设计 审计报告

## 总评

PIM 是一个边界相对清晰的本地单体（FastAPI + SQLite + APScheduler + React/Tauri SPA）。文档（ARCHITECTURE.md、ADR-001/003/004）质量高，与代码主干一致。后端 13 个二级目录的命名（`api / collectors / pipeline / processors / services / tasks / models / schemas / migrations / middleware / utils / exporters / ai`）划分合理，整体走向**Big Ball of Mud 的风险尚未到来**。但在 lifespan 启动顺序、coordinator 错误吞噬以及 `services/` 与 `tasks/` 边界模糊等方面有改进空间。

## 严重问题（❌）

无严重架构问题。

## 轻微问题（⚠️）

- **L1** coordinator 单条目失败被静默吞噬（`backend/app/pipeline/coordinator.py:91-93`）。
- **L2** `tasks/maintenance.py` 与 `tasks/maintenance_tasks.py` 双文件并存，职责未在文档中分清。
- **L3** ADR-004 自陈"目标态尚未落地"，前后端 features 仍是双份 + CI 比对，存在漂移风险。
- **L4** lifespan 中 `await asyncio.to_thread(run_migrations)` 之外还隐式启动调度器、队列、Playwright，shutdown 顺序虽有显式 try/except，但首段任意步骤抛异常即会让进程半启动。

## 良好实践（✅）

- **G1** 启动失败会向上抛——`run_migrations()` 失败即 lifespan 失败、FastAPI 不接受流量（`backend/app/main.py:93`），符合 fail-fast 原则。
- **G2** `lifespan` 关闭顺序考虑到了 Playwright 子进程的回收，避免重启泄漏 Chromium（`backend/app/main.py:160-165`）。
- **G3** SSL 关闭、Playwright/X 实验性开关均在启动期 logger.warning，运维可观测（`backend/app/main.py:122-150`）。
- **G4** ARCHITECTURE.md 与代码版本完全对齐（probe_strategies/registry、hourly_digest 拆包、reader/streaming 等），文档不是装饰品。
- **G5** ADR 文档全部写明"触发重评估的条件"，体现长期可演进的架构治理思维。

## 详细审计清单

### 1. main.py 启动逻辑：迁移 / 调度器 / 队列顺序与 fail-fast

- **结论：** ✅（顺序合理）+ ⚠️（关闭路径细节）
- **代码位置：** `backend/app/main.py:89-174`
- **分析：**
  - 启动顺序：迁移 → 恢复 metrics 检查点 → 启动 APScheduler & 触发 startup jobs → 启动 TaskQueue worker → 打印启动信息（L93-120）。这是正确的：先把 schema 推到目标版本，再启动会读写 DB 的调度器与 worker。
  - 迁移用 `asyncio.to_thread(run_migrations)`，没有捕获异常 → 失败后整个 lifespan 失败 → uvicorn 不会接受流量。这是 fail-fast 的正确姿势。
  - 关闭路径：`scheduler.shutdown(wait=False)` → `task_queue.stop_workers()` → `shutdown_browser_pool()` → `persist_metrics()` → `async_engine.dispose()`（L154-174），顺序正确（先停生产者、再停消费者、再清理资源）。
  - 但**启动期 setup_scheduler / scheduler.start / trigger_startup_jobs 三个连续调用没有任何 try/except**（L104-106）。如果 `trigger_startup_jobs()` 抛错，TaskQueue 不会启动；这次是设计选择（fail-fast），但日志中没有 startup 阶段的"上一步走完了"打点，排查启动失败时只能从堆栈倒推。
- **建议：**
  - 给启动期每个外部子系统（scheduler、taskqueue、browser_pool）加一行 `logger.info("starting %s", "scheduler")`/`logger.info("started %s", ...)` 包裹，使排障更友好。

### 2. pipeline/coordinator.py：阶段接口契约 / 错误传播

- **结论：** ⚠️
- **代码位置：** `backend/app/pipeline/coordinator.py:20-234`
- **分析：**
  - 各阶段（CollectorStage / NormalizerStage / StorageStage）均通过 `execute()` 静态方法暴露，调用约定一致，是合理的 Stage 模式。
  - 错误传播采用"软错误"模型：collector 层通过元组 `(raw_contents, merged_warning, primary_warning)` 把警告/错误带回（L165, L178）；coordinator 把这些转化为 `source.error_count` 递增和 `last_fetch_outcome`（L98-119 `_update_source_status`）。这是与 ADR 一致的设计。
  - **但单条目级的硬错误被吞**：`_build_raw_content_objects` 第 91-93 行 `except Exception as exc: logger.error(...); continue`，单条 build 失败既不计入 `error_count` 也不出现在返回值，外层只能从日志看到。在大批量抓取里这会让"为什么少了几条"变成黑箱。
  - `StorageStage.execute(db, content_objects)`（L207）没有 await：StorageStage 是同步实现可以接受，但与上面的 `await CollectorStage.execute(...)` / `await NormalizerStage.execute(...)` 风格不统一，看代码时容易误以为漏了 await。
- **建议：**
  - 把 `_build_raw_content_objects` 失败计数累加到返回结果中（例如返回 `build_failed` 字段），让 fetch_tasks 能在日志里输出 `saved=N stale_skipped=M build_failed=K`。
  - StorageStage 要么改造为协程并 `await`，要么在协程里显式注释"sync intentional"，统一阅读心智。

### 3. ADR-001 单体边界 / Big Ball of Mud 风险

- **结论：** ✅
- **代码位置：** `docs/ADR-001-local-monolith.md`、`docs/ARCHITECTURE.md:124-138`、`backend/app/`
- **分析：**
  - 顶层目录划分干净（api、pipeline、collectors、processors、services、tasks、models、schemas、migrations、middleware、utils、exporters、ai）。每层职责文档化（ARCHITECTURE.md 表 §4）。
  - coordinator.py 多处用**函数内 lazy import**（L28、L64、L107、L122、L160-162）规避循环依赖。这本身是 Big Ball of Mud 早期信号，但目前局部使用、注释合理（L159 "Import stages lazily to avoid circular import"），尚不严重。
  - ADR-001 显式承认权衡（横向扩展、SQLite 写并发、复杂队列编排）并定义了重评估条件，治理姿态健康。
- **建议：**
  - 把 lazy import 数量控制在"只用于打破循环"，不要扩展到性能优化场景；建议在 `pipeline/__init__.py` 留 TODO 跟踪现有几处。

### 4. ADR-004：功能标志集中管理

- **结论：** ⚠️
- **代码位置：** `backend/app/features.py`、`frontend/src/features.ts`、`docs/ADR-004-feature-flags.md`
- **分析：**
  - 后端集中在 `backend/app/features.py`（main.py:136 引用 `playwright_enabled`、`x_playwright_enabled`），单一来源。
  - 前端有独立副本 `frontend/src/features.ts`（ADR-004 自陈），靠 CI 比对脚本防漂移。
  - ADR-004 状态："已记录（2026-04-01），待实施"——目标态（`/api/config/features` 端点 + 前端运行时拉取）尚未落地，过渡期已持续 1 个月。
  - 风险：CI 一致性脚本只校验 Flag 名称集合，不校验默认值，仍可能出现"前端默认 enabled、后端默认 disabled"的语义漂移。
- **建议：**
  - 推动落地 ADR-004 目标态；如果短期不打算实施，把 CI 脚本扩展为同时校验默认值。

### 5. services/ 与 tasks/ 职责重叠

- **结论：** ⚠️
- **代码位置：** `backend/app/services/`（14 个文件）、`backend/app/tasks/`（9 个文件）
- **分析：**
  - 主流分层是清晰的：`tasks/*` 调用 `services/*`（编排 vs 业务）。例如 `tasks/hourly_digest_tasks.py` 编排 `services/hourly_digest/*` 的纯业务函数，符合 ARCHITECTURE.md §2 描述。
  - 但 `tasks/` 下出现两个**职责相近**的文件：
    - `tasks/maintenance.py`
    - `tasks/maintenance_tasks.py`
    无法仅从文件名判断分工，需要打开看实现。文档未提及二者关系，是技术债迹象。
  - `tasks/fetch_orchestrator.py` + `tasks/fetch_tasks.py` + `tasks/fetch_auth_helpers.py` 是合理的"orchestrator + 任务入口 + helper"三段式，命名清晰。
  - `services/api_config_credentials.py`（凭据）与 `api/configs_api_auth.py`（API 路由）有名字相似但分层正确：service 实现、api 暴露 HTTP。
- **建议：**
  - 合并 `tasks/maintenance.py` 与 `tasks/maintenance_tasks.py`，或在文件顶部 docstring 明确二者分工。
  - 在 ARCHITECTURE.md §4 表里加一行说明 `tasks/` 子模块的命名约定（`*_tasks.py` = 调度入口；其它 = helper）。

## 涉及文件

- `backend/app/main.py`
- `backend/app/pipeline/coordinator.py`
- `backend/app/features.py`（通过 main.py:136 引用确认）
- `backend/app/services/`（目录列表 ls 得到 14 个 .py）
- `backend/app/tasks/`（目录列表 ls 得到 9 个 .py）
- `docs/ARCHITECTURE.md`
- `docs/ADR-001-local-monolith.md`
- `docs/ADR-003-auth-credentials.md`
- `docs/ADR-004-feature-flags.md`
