# 模块六：数据库与并发 审计报告

## 总评

DB 层基础姿态正确：
- SQLite 启用 WAL（`backend/app/database.py:47, 56`）解决"读不阻塞写、写不阻塞读"；
- foreign_keys ON 强制外键；
- busy_timeout=5s 缓解并发写入争用；
- async_engine 通过 `expire_on_commit=False` 避免 async session 反复重新加载；
- Content 模型有 `(source_id, external_id)` 唯一约束 + 多个针对查询模式的索引；
- Alembic 迁移在启动期 fail-fast，老数据库（pre-Alembic）会被识别并 stamp head。

**主要弱点：**（1）async_engine **没有显式 pool 配置**，使用 SQLAlchemy 默认 pool_size=5 + max_overflow=10——这在 SQLite 写入语义下不必要，且可能让 BUSY 错误在重复重试中放大；（2）runtime_lock 服务**没有自动续期机制**，TTL 内任务超时会被其它 worker 抢锁；（3）过期锁只能依赖手动调 `purge_expired`，没有调度任务回收；（4）`original_url` 列没有唯一索引，URL canonicalization 漂移时可能产出重复行（详见模块三 L3）；（5）migrations 在每次启动都跑 `command.upgrade(..., "head")`，没有"only-on-fresh-db" 跳过路径——多次重启不构成问题，但不必要的进程开销。

## 严重问题（❌）

无严重错误。

## 轻微问题（⚠️）

- **L1** `async_engine` 没有显式 pool 配置（`backend/app/database.py:37-40`），使用 SQLAlchemy 默认 pool_size=5 + max_overflow=10。SQLite 不支持真正的并发写，pool 多于 1 主要是为读并发，应当显式注释这个选择。
- **L2** `RuntimeLockService` 没有自动续期机制：长任务（> TTL）会被另一个 worker 抢锁（`backend/app/services/runtime_lock_service.py:29-53`）。
- **L3** `RuntimeLockService.purge_expired` 没有被任何调度任务定期调用（grep 验证仅 `is_locked` 单条遇到时回收）；过期锁会积累。
- **L4** `Content.original_url` 没有 unique index（`backend/app/models/content.py:38`）；只有 `(source_id, external_id)` unique。无 external_id 的源（罕见）可能产出 URL 重复行。
- **L5** `run_migrations` 每次进程启动都执行 `command.upgrade(cfg, "head")`，不区分"已是 head"与"需要升级"——alembic 内部会快速识别已是 head 然后 noop，但启动多花 50-200ms。
- **L6** `_set_sqlite_pragma_*` 监听 `connect` 事件，每次新连接都设置 PRAGMA。WAL 是 DB 级别（一次设定永远生效），foreign_keys 和 busy_timeout 是连接级别。重复设 WAL 实际是 noop 但可以打日志区分。
- **L7** Alembic 自动迁移的回滚路径不在文档中：万一 migration 文件存在 bug，启动期 crash 后用户没有"--no-migrations" 启动选项可用。

## 良好实践（✅）

- **G1** WAL 模式启用：`PRAGMA journal_mode=WAL`（`database.py:47, 56`），允许并发读 + 单写者，是 SQLite 多连接场景的最佳设置。
- **G2** `PRAGMA foreign_keys=ON`（`database.py:48, 57`）强制外键约束（SQLite 默认 OFF）。
- **G3** `PRAGMA busy_timeout=5000`（`database.py:49, 58`）让 SQLite 在写争用时等 5 秒，避免立刻抛 SQLITE_BUSY。
- **G4** AsyncSession 用 `expire_on_commit=False`（`database.py:69`）避免 async 路径每次 commit 后重新 lazy-load。
- **G5** `get_db`/`get_async_db` 都有 try/finally 保证 session 关闭（`database.py:77-92`）。
- **G6** Content 模型 `(source_id, external_id)` 唯一约束（`models/content.py:19`）配合采集器侧的 external_id 生成逻辑，构成完整的去重链路。
- **G7** Content 索引覆盖业务查询：`(source_id, external_id)`、`created_at`、`publish_time`、`fetched_at`、`updated_at`（`content.py:20-24`）。
- **G8** `migrations.py` 显式处理三种状态：(a) 已有 alembic_version → upgrade head；(b) legacy schema → stamp head + 补建 RuntimeLock；(c) 全新 → upgrade head（`migrations.py:45-69`）。是稀有的细致迁移引导。
- **G9** `RuntimeLockService` 使用 INSERT 失败 → fall through 到 UPDATE 已过期行的原子模式（`runtime_lock_service.py:34-53`），避免 check-then-act 竞争。
- **G10** `RuntimeLockService.release` 校验 `owner_id` 一致才删除（`runtime_lock_service.py:57-65`），避免错释别人的锁。
- **G11** Alembic 自动迁移在 lifespan 早期执行（`main.py:93`）→ 失败即 lifespan 失败 → uvicorn 不接受流量 → fail-fast。

## 详细审计清单

### 1. database.py：连接池大小 / WAL 启用

- **结论：** ⚠️
- **代码位置：** `backend/app/database.py:30-40`
- **分析：**
  - sync engine：`create_engine(url, connect_args={"check_same_thread": False})`，没有显式 pool 设置 → 默认 QueuePool（pool_size=5, max_overflow=10）。
  - async engine：`create_async_engine(url)` 同样无显式 pool 设置 → aiosqlite + 默认池。
  - SQLite WAL 允许多 reader 并发，pool_size=5 对读路径有意义（FastAPI 多并发请求）；写路径 SQLite 仍是序列化的，多个连接同时写会撞 busy_timeout 等待。
  - 没有 SQLite 专用的 `poolclass=NullPool` 或显式注释，看代码会让人疑惑"为什么用普通 QueuePool"。
- **建议：**
  - 在 create_async_engine 加显式 `pool_size=5, max_overflow=0, pool_pre_ping=True` 并注释"reads scale with WAL; writes still serialise"。
  - 或者改为 `poolclass=NullPool` 然后让 OS 文件锁 + WAL 处理一切（更简单但每次新建连接，重复 PRAGMA 设定）。

### 2. Session 管理：生命周期 / 泄漏

- **结论：** ✅
- **代码位置：** `backend/app/database.py:77-92`、所有 `Depends(get_async_db)` 调用
- **分析：**
  - 主要 API 路由通过 `db: AsyncSession = Depends(get_async_db)` 拿 session，FastAPI 的 dependency 在请求结束时自动 close（`get_async_db` 用 async with + finally）。
  - 同步路径（`fetch_tasks`、`runtime_lock_service`）用 `with SessionLocal() as db:` 模式，also auto-close。
  - **没看到** 长持有 session 不 close 的反模式。
  - **未在本次审计验证：** lifespan 内或 startup hook 内是否有遗漏的 `engine.connect()` 不 dispose 的代码。
- **建议：** 可以加一个 lifespan-shutdown 时的 `engine.dispose()` 计数日志（已部分有：`async_engine.dispose()` 在 `main.py:174`）。

### 3. 模型设计：外键 / 级联

- **结论：** ✅（基础）+ 未在本次审计验证级联策略
- **代码位置：** `backend/app/models/content.py`、`backend/app/models/source.py`、其它 9 个模型
- **分析：**
  - PRAGMA foreign_keys=ON 已启用 ✅。
  - Content 表声明 `ForeignKey` 到 source（grep 验证 `from sqlalchemy import ... ForeignKey`）。
  - **未审计：** 各 ForeignKey 的 `ondelete=` 子句。配置-认证关系在 `configs_api_auth.delete_auth_config`（已在模块二审过）是手动级联（先 NULL Source.auth_config_id 再 delete config）。其它表对的级联策略需要逐表验证。
- **建议：**
  - 对每个 ForeignKey 显式指定 `ondelete="CASCADE"` 或 `ondelete="SET NULL"`，不依赖 SQLAlchemy 默认。

### 4. RuntimeLockService：TTL / 续期 / 自动释放

- **结论：** ⚠️
- **代码位置：** `backend/app/services/runtime_lock_service.py:29-95`
- **分析：**
  - 锁机制：INSERT 新行（unique key）→ IntegrityError → 改为 update expired row → 没有 update（即未过期且非己方）则 acquire 失败。原子且无 TOCTOU。✅
  - **TTL 由调用方传入**，没有自动续期（heartbeat）。如果一次 fetch 任务用 600s TTL 但执行了 700s，第 600s 后另一个 worker 可以 acquire 同名锁——两个 worker 并发跑同一逻辑。
  - **释放路径** `release` 只删除自己 owner 的行 → 别人不会把别人的锁释放。✅
  - `is_locked` 在发现行已过期时主动 delete（L73-77）——是一种 lazy purge。
  - `purge_expired` 是手动 API，**没有定期调度**（grep 在 `app/scheduler.py` 与 tasks 中找不到调用方）。过期锁会一直留着直到下次有人对该 key `is_locked` 或 `acquire`。考虑到锁数量有限（fetch / digest 等几个），增长缓慢，但仍是 leak。
- **建议：**
  - 增加 `acquire_with_heartbeat` API：用一个后台 task 每 TTL/3 时间 update 自己的 expires_at。
  - 把 `purge_expired` 注册为 maintenance scheduled job（每天一次）。

### 5. Alembic 迁移：自动执行 / 数据丢失风险

- **结论：** ⚠️
- **代码位置：** `backend/app/migrations.py:45-69`、`backend/app/main.py:93`
- **分析：**
  - 启动期 lifespan **总是**调 `run_migrations()` → `command.upgrade("head")`。这是单进程本地应用的简单做法。
  - 已迁移的 DB 跑 upgrade head 是 noop，但 Alembic 仍要打开 connection、读 alembic_version 表、和 head revision 比较——典型耗时 50-200ms。
  - **数据丢失风险评估：**
    - 迁移文件本身的质量决定数据是否会丢——本次审计未逐个迁移看 ALTER TABLE 是否有 DROP COLUMN（SQLite 上 alembic 通常用 batch 方式重建表）。
    - `pim` CLI 在每次 `pim start` 前都会 `pim backup`（按 ARCHITECTURE.md §7 描述）；如果用户先 backup 再 start，灾难恢复路径是有的。
    - 没有"--skip-migrations" 或 "--dry-run" 启动选项，运维人无法在怀疑 migration 出问题时跳过它启动 read-only。
  - 老 DB（pre-Alembic）的 stamp head 路径假设 schema 与 alembic head 相同，否则 stamp 后下次 upgrade 不会触发任何变更，schema drift 会持续未察。
- **建议：**
  - 加 `PIM_MIGRATIONS_SKIP=true` 环境变量旁路；用于紧急启动检视 DB。
  - 在 stamp head 之前比较实际 schema 与 head 版本预期 schema，警告差异。

### 6. Content 去重：URL 唯一索引

- **结论：** ⚠️
- **代码位置：** `backend/app/models/content.py:19-23`
- **分析：**
  - `UniqueConstraint('source_id', 'external_id', name='uq_content_source_external_id')` ✅ 是核心去重约束。
  - external_id NULL 时不参与唯一约束（SQLite NULL 处理）→ 没有 external_id 的内容可重复存。
  - `original_url` 是 Text 不带 unique index → 同一 URL 在同一 source 内可以多次存在（如果 external_id 不同或为 NULL）。
  - 这与模块三 L3 的 `dedupe_raw_contents` URL canonicalization 缺失串联：内存批次去重不规范化 URL，DB 也不强制 URL 唯一 → 罕见情况下同 URL 多行。
  - **并发写入：** SQLite WAL 让多写者排队；UniqueConstraint 是 atomic check，第二个 INSERT 会抛 IntegrityError → 调用方需 catch。Coordinator 的 `dedupe.handle_external_id_duplicate` 是显式 select-then-update 模式（L32-46），不靠 INSERT-on-conflict。但如果两个并发 fetch 任务同时跑同一 source 的同一 external_id，两个 select 都看不到 existing → 两个都尝试 INSERT → 第二个抛 IntegrityError。
- **建议：**
  - 给 `original_url` 加 `Index('ix_content_source_url', 'source_id', 'original_url')`（非 unique，加速 reader 查询）。
  - 如果决定 URL 也要 unique-per-source，在 normalizer 把 URL canonicalize 后加 partial unique constraint。

### 7. SQLite WAL 模式：读写并发

- **结论：** ✅
- **代码位置：** `backend/app/database.py:44-59`
- **分析：**
  - WAL 同时启用在 sync 和 async 引擎的 connect 事件（L44-59）。WAL 是 DB 级别 PRAGMA：第一次设定后会写入 DB header，后续连接自动用 WAL，不需要重复设置。但代码每次 connect 都设——这是 noop，无害。
  - busy_timeout=5000 是 connection 级别，确实需要每个 connection 设。
  - **读并发：** WAL 下，写者占有 mutex 不会阻塞读者；多 reader + 单 writer 模型对 PIM 的工作负载（读>>写）很合适。
  - **写并发：** 仍是序列化的（SQLite 的单写者约束）。fetch_concurrency=20 + AI 处理 + cleanup 同时写时，第 21+ 写会等 busy_timeout=5s。如果 5s 内没轮到，抛 SQLITE_BUSY。
- **建议：**
  - 监控 SQLITE_BUSY 错误（建议加 metrics counter）；如果常见，把 fetch task 改为聚合写（batch insert）。

### 8. 长事务：AI 处理与内容存储

- **结论：** ✅
- **代码位置：** `backend/app/pipeline/coordinator.py:154-234`、`backend/app/processors/content_processor.py`
- **分析：**
  - **fetch 路径不调 LLM**（模块四验证），所以 collect → normalize → store 的整个事务里没有 LLM 阻塞，单事务时长是普通 SQL 操作的累计时间，毫秒级。
  - `dedupe.handle_external_id_duplicate` 显式声明"不在此 commit、由 coordinator 在 batch 边界提交"（dedupe.py:26-31），保证整 batch 共享一个事务（同模块三 G5）。
  - reprocess_content / reader 的翻译路径单独跑（不在 fetch 主路径），不与 fetch 共享事务。
  - **唯一可能的长事务**是 reader 的 `persist_reader_translation_cache`（streaming.py:184-195），写入翻译缓存。这一步是单行更新，事务短。
- **建议：** 无；保持"fetch 路径不持长事务"的不变量。

## 涉及文件

- `backend/app/database.py`
- `backend/app/migrations.py`
- `backend/app/services/runtime_lock_service.py`
- `backend/app/models/`（10 个模型文件，通过 grep 抽样核验 Content 模型）
- `backend/alembic/versions/`（13 个迁移文件，未逐个审）
- `backend/app/main.py:93`（lifespan 中迁移调用）
