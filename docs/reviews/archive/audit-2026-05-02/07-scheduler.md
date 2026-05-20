# 模块七：任务调度与队列 审计报告

## 总评

调度系统采用 APScheduler 单进程方案 + 自研 `BoundedTaskQueue`（200 容量、4+4 worker）+ 数据库 RuntimeLock 协调，结构清晰：
- 8 个定时任务覆盖 fetch、digest、email、cleanup 四类；
- TaskQueue 在队列满时不静默扩容、而是丢弃 + 写 DLQ 日志（`data_dir/dropped_tasks.log`）+ 计数到 metrics；
- worker 捕获单任务异常用 `logger.exception` 记录但不退出；
- shutdown 优雅 cancel + gather；
- 时区显式设 `Asia/Shanghai`，cron 触发器使用本地时间语义；
- maintenance_tasks 含错误恢复逻辑（成功后 24 小时无新错则 reset error_count）。

**主要弱点：**（1）8 个 add_job 都**没有显式设 `max_instances`、`misfire_grace_time`、`coalesce`**——靠 APScheduler 默认（max_instances=1 ✅、misfire_grace_time=1s ⚠️、coalesce=False ⚠️），意味着应用 down 超过 1 秒就会让 cron 任务静默错过；（2）SMTP 失败**无重试**，单次失败即放弃；（3）fetch 与 process 用同一 `BoundedTaskQueue` 实例的两条独立队列 + 各 4 worker，物理上**互不阻塞**——但都跑在主 event loop 上，CPU 密集任务（不存在）会互相阻塞；（4）TaskQueue 没有"重启时把还没完成的任务读回来"的持久化路径——崩溃中的任务永久丢失。

## 严重问题（❌）

无严重错误。

## 轻微问题（⚠️）

- **L1** `scheduler.py` 8 个 `add_job` **全部**没有显式 `misfire_grace_time` 与 `coalesce`，默认值分别是 1s 与 False，进程重启或卡 1s 以上即静默错过 cron 任务（`backend/app/scheduler.py:29-99`）。
- **L2** SMTP 发邮件失败仅 `except Exception as e: logger.error`（`backend/app/tasks/email_tasks.py:53`），**没有重试**。单次网络抖动即丢失日报/医生报告，不会自动补发。
- **L3** TaskQueue 任务持久化缺失：进程崩溃时 in-flight + queued 任务丢失，重启后没有"恢复未完成 fetch"路径（`backend/app/tasks/task_queue.py:1-122`）。
- **L4** `cleanup_old_content` 默认 `retention_days=90` 是硬编码（`backend/app/tasks/maintenance_tasks.py:12`），不通过 system_settings 暴露给用户，要修改必须改代码。
- **L5** `cleanup_error_logs` 的"恢复"条件是 `last_fetched_at > now - 24h AND last_error == None`（`maintenance_tasks.py:53-58`），意味着持续每 5 分钟成功 fetch 但 last_error 在某个瞬间被改为 NULL 才能 reset；逻辑上 last_error 在每次 success fetch 都会被设为 None，所以条件成立。但 trigger 周期是每 6 小时一次（`scheduler.py:78`），错误计数最多滞后 6 小时才被清。
- **L6** `trigger_startup_jobs` 在每次启动都补跑 `generate_previous_hour_digest` 一次（`scheduler.py:103-111`）——这意味着开发期频繁重启会反复重跑摘要 LLM 调用。需要 idempotency 保证（应该有但未在 hourly_digest_tasks 内验证）。
- **L7** 8 个 `add_job` 共享 default `max_instances=1`，但**没有显式声明**——下一次升级 APScheduler 默认变更时可能悄悄破坏 fetch 重叠保护。

## 良好实践（✅）

- **G1** TaskQueue 满时**显式丢弃 + 持久化到文件 DLQ**（`task_queue.py:34-43`），运维人员可以从 `data_dir/dropped_tasks.log` 重放。
- **G2** TaskQueue 丢弃事件也计入 `task_queue_metrics`（L56, 70），可被 `/metrics` 端点观测。
- **G3** Worker 单任务失败用 `logger.exception`（含 traceback）记录但不退出（`task_queue.py:98-99, 112-113`）——单坏行为不会让 worker 池缩水。
- **G4** Worker `asyncio.CancelledError` 显式 break（L102, 116），`stop_workers` 用 `gather(return_exceptions=True)` 不让一个 cancel 失败拖垮 shutdown（L82-89）。
- **G5** Scheduler 时区显式 `Asia/Shanghai`（`scheduler.py:13`），所有 CronTrigger（"hour=8 minute=0"）都是 CST 语义，不会因为 UTC 默认导致用户在错误时段收到日报。
- **G6** `cleanup_old_content` 保护 favorited 与 archived 内容不被清理（`maintenance_tasks.py:24-27`）——保留用户主动标记的资料。
- **G7** `purge_expired_runtime_locks` 注册为定期任务（`scheduler.py:84-90`，每小时 minute=15）——回应了模块六关于"没有调度回收"的疑虑，实际是有的。
- **G8** `cleanup_error_logs` 在 6 小时周期内自动恢复 source 的 error_count，配合模块三的指数退避形成"成功一次→reset"的恢复循环（虽不完美，但有自愈）。
- **G9** Hourly digest 有三层 fallback：LLM 选稿失败 → 第二次重试 → 本地 RankingService（参考 `hourly_digest_tasks.py:161-185` 的 noqa 注释，"both AI paths failed; fall through to path 3"）。
- **G10** `BoundedTaskQueue` 是 fetch 与 process 两条**独立队列**（`task_queue.py:19-20`），fetch worker 拥塞不会饿死 process worker。

## 详细审计清单

### 1. scheduler.py：8 任务的 max_instances / 重叠保护

- **结论：** ⚠️
- **代码位置：** `backend/app/scheduler.py:16-100`
- **分析：**
  - 8 个 `add_job` 调用：
    - check_and_fetch_due_sources（5 min）
    - generate_hourly_digest（每小时 minute=0）
    - send_daily_digest_emails（8:00）
    - send_doctor_digest_email（8:05）
    - cleanup_old_content（周日 3:00）
    - cleanup_error_logs（每 6 小时 minute=30）
    - purge_expired_runtime_locks（每小时 minute=15）
    - run_markdown_export（每小时 minute=30）
  - **没有任何 `max_instances=1` 显式声明**。
  - APScheduler `AsyncIOScheduler` 的 default 是 `max_instances=1`（每个 job 同时只能跑 1 个实例），所以**实际上有重叠保护**。但默认值依赖第三方库——升级时可能变。
- **建议：** 给所有 add_job 显式加 `max_instances=1`，并在仓库 ARCHITECTURE.md §4 表格里注明。

### 2. fetch_tasks.py：源到期检查时区处理

- **结论：** ✅
- **代码位置：** `backend/app/scheduler.py:13`、`backend/app/collectors/base.py:61-69`
- **分析：**
  - Scheduler 全局时区 `Asia/Shanghai`，所有 CronTrigger 都是 CST。
  - `BaseCollector.should_fetch` 用 `utcnow_naive()` 与 `last_fetched_at`（naive UTC）相加 timedelta(minutes=fetch_interval)。这是**duration 计算**，与时区无关。
  - 即使数据库里的时间是 naive UTC，与"东八区下午 3 点跑 cron"也兼容——cron 决定何时启动 worker，worker 内部判断 source 是否到期是基于 last_fetched_at 与 now 的差值。
- **建议：** 无；保持时区显式声明的好习惯。

### 3. task_queue.py：队列满 / 背压

- **结论：** ✅
- **代码位置：** `backend/app/tasks/task_queue.py:45-71`
- **分析：**
  - `enqueue_fetch` / `enqueue_process` 用 `put_nowait` → 满则抛 QueueFull → catch 后 (1) logger.warning、(2) 写 DLQ 文件、(3) 增加 metrics、(4) 返回 False 让调用方决策。
  - 调用方（`fetch_tasks.check_and_fetch_due_sources`、`process_tasks` 等）拿到 False 可以选择稍后重试或忽略。
  - DLQ 文件路径：`data_dir/dropped_tasks.log`（追加写）。⚠️ 没有日志轮转，长期运行会无限增长（与模块十的"日志轮转"问题同源）。
- **建议：**
  - 给 dropped_tasks.log 加大小阈值（> 50 MB 时保留尾 10 MB），或者挂一个 daily rotate。

### 4. hourly_digest_tasks.py：失败影响下次触发？

- **结论：** ✅
- **代码位置：** `backend/app/tasks/hourly_digest_tasks.py`（grep 结果验证）
- **分析：**
  - 多路径 fallback：path1 LLM → path2 LLM 重试 → path3 本地 RankingService（noqa 注释 "both AI paths failed; fall through to path 3"）。
  - 任务函数本身正常返回 → APScheduler 不会因为单次失败禁用下次触发。
  - APScheduler `max_instances=1` 默认保证：上一小时摘要还没结束时下一小时不会重叠跑——但这种情况下下一小时直接 skip 而非排队。需要 ⚠️ 监控这个。
- **建议：** 如果观察到摘要任务 > 1 小时，应该限制 LLM 总用时（已有 75s + max_tokens 800，但 path3 兜底很快）。

### 5. email_tasks.py：SMTP 失败重试

- **结论：** ⚠️
- **代码位置：** `backend/app/tasks/email_tasks.py:21-53, 216-247`
- **分析：**
  - `aiosmtplib.send`（推断自代码风格）一次失败就 `logger.error`，**没有重试**。
  - SMTP 未配置时直接 skip + warn——是良好的"未配置不爆炸"姿势。
  - 没有发送失败入库记录的机制（grep 结果中没有 `EmailSchedule.last_error` 等字段更新逻辑可见）。
- **建议：**
  - 加 1-2 次重试 with exponential backoff（5s, 30s）；仍失败时把错误写入 EmailSchedule.last_error 字段。

### 6. maintenance_tasks.py：清理条件 / 误删风险

- **结论：** ✅（基础正确）+ ⚠️（参数不可调）
- **代码位置：** `backend/app/tasks/maintenance_tasks.py:12-39`
- **分析：**
  - `cleanup_old_content`：`Content.created_at < cutoff AND favorited == False AND archived == False`（L24-28）→ 保护用户标记的内容。✅
  - `synchronize_session=False` 跳过 ORM session 同步（性能），SQLite 上 OK。
  - 单事务：`db.delete()` + `db.commit()`，错误时 rollback。
  - `retention_days=90` 是函数默认参数，没有从 settings/system_settings 读取——用户必须改代码才能调整。
- **建议：**
  - 把 retention_days 加到 `system_settings`（`content_retention_days`），运行时可调。
  - 在删除前打印 dry-run 计数（"would delete N items"）便于运维确认。

### 7. 崩溃恢复：misfire_grace_time

- **结论：** ⚠️
- **代码位置：** `backend/app/scheduler.py:29-99`
- **分析：**
  - 没有任何 `add_job` 显式设 `misfire_grace_time`。APScheduler 默认是 **1 秒**——即如果触发时间到了但调度器忙/未启动 1 秒以上，下次启动会**直接跳过该次触发**而不补跑（除非加了 `coalesce=True`）。
  - PIM 部署在用户笔记本上，挂起/重启很常见。每次重启 > 1 秒就会让所有"应该跑过的"cron 任务静默错过。
  - `trigger_startup_jobs` 部分弥补了 hourly digest（启动时 best-effort 补跑），但其它任务（每周 cleanup、daily email、6h cleanup_error_logs）没有补跑。
  - daily digest 错过 8:00 的话，用户当天就收不到邮件，第二天才会再发——8 点起床的用户不会注意到，但仍是数据丢失。
- **建议：**
  - 为周期长、对延后容忍的任务加 `misfire_grace_time=3600`（1 小时）+ `coalesce=True`：错过的 cron 在恢复后立即合并跑一次。
  - 频繁触发（每 5 分钟、每小时 minute=15/30）的任务用 `misfire_grace_time=300` 即可。

### 8. 任务隔离：fetch 与 process 共用工作线程池？

- **结论：** ✅
- **代码位置：** `backend/app/tasks/task_queue.py:15-122`
- **分析：**
  - `BoundedTaskQueue` 内部有**两条独立的 asyncio.Queue**（`_fetch_queue`、`_process_queue`），各自 200 容量。
  - 4 fetch worker + 4 process worker 是**独立的 `asyncio.Task`**（`start_workers` L73-80），各自 `await` 自己的队列。
  - 两类 worker 都跑在同一个 event loop（FastAPI 的主 loop），这意味着：
    - I/O 密集（绝大多数）：互不阻塞 ✅
    - CPU 密集（如果有）：会争抢 event loop 时间 → 互相变慢
    - 长时间不让出（synchronous）：会卡住整个 event loop
  - PIM 中 fetch 主要是 aiohttp/playwright（I/O），process 也是 I/O（DB + 可选 LLM）。`asyncio.to_thread` 在 maintenance_tasks 中被显式用于把同步 SQLAlchemy 操作丢到线程池，避免阻塞 event loop（`maintenance_tasks.py:39, 69, 109`）。✅
- **建议：** 无；继续保持"任何同步 SQLAlchemy 操作都用 asyncio.to_thread"的不变量。

## 涉及文件

- `backend/app/scheduler.py`
- `backend/app/tasks/task_queue.py`
- `backend/app/tasks/maintenance_tasks.py`
- `backend/app/tasks/fetch_tasks.py`（grep 结果，模块三已读详细）
- `backend/app/tasks/hourly_digest_tasks.py`（grep 结果）
- `backend/app/tasks/email_tasks.py`（grep 结果）
- `backend/app/utils/metrics.py`（task_queue_metrics 引用）
