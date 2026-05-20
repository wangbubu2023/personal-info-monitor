# 模块三：数据采集流水线 审计报告

## 总评

采集层结构清晰：5 类采集器（rss、website、x_twitter、youtube、podcast）继承 `BaseCollector`，pipeline 三阶段（CollectorStage → NormalizerStage → StorageStage）由 coordinator 串联，外部资源（Playwright）通过精心设计的 `browser.py` 池管理。整体**错误隔离很好**——单 URL 失败、单条目处理失败都不会让整个 pipeline 中断。

主要问题：（1）`BaseCollector` 没在接口层定义 timeout/retry/error 约束，靠子类自觉；（2）`collector_stage` 在 fetch 循环中临时改写 `source.url` 是 fragile 的副作用模式；（3）`dedupe_raw_contents` 内存级去重缺 URL canonicalization，可能让 `.../article` 与 `.../article/` 同时入库；（4）`error_count` 只用于指数退避，**没有阈值禁用与自动恢复机制**——长期不可访问的源会一直被慢速重试。

## 严重问题（❌）

无严重错误。

## 轻微问题（⚠️）

- **L1** `BaseCollector` 抽象类只定义 `fetch(source)` 签名，未在文档/类型层规定超时、重试、异常返回模型，导致每个子类自由发挥。
- **L2** `CollectorStage.execute` 在 `for fetch_url in source_urls` 中临时改写 `source.url`（`backend/app/pipeline/collector_stage.py:114-124`），用 `try/finally` 复原；这是 fragile 的副作用模式，并发场景或异常路径上易出问题。
- **L3** `dedupe_raw_contents`（`backend/app/pipeline/utils.py:210-220`）按 `external_id || url || title` 去重，但**对 URL 不做 canonicalization**（trailing slash、query string、fragment、http→https 重定向后的 URL 都不会被合并）。
- **L4** `error_count` 只驱动指数退避（`backend/app/tasks/fetch_tasks.py:180` `backoff = 1 << min(error_count, 5)`），**没有触达阈值后自动 disable 源的机制**。长期失败的源会一直被以 32 倍间隔的 backoff 重试。
- **L5** `_build_raw_content_objects` 单条 build 失败被 logger.error + continue 后没有计数（`backend/app/pipeline/coordinator.py:91-93`）——审计模块一已提及，pipeline 上游也存在同模式（`collector_stage.py:120-122`）。
- **L6** `NormalizerStage` 静默 stale gate 默认值在源类型间差异很大（X 60 分钟，feed-like 7 天，manual 7 天），但配置入口 `metadata["max_fetch_lag_minutes"]` 没在 ARCHITECTURE.md 中显式说明。

## 良好实践（✅）

- **G1** 多 URL fetch 错误隔离：单 URL 抛错只 `logger.error + continue`，不影响其它 URL（`collector_stage.py:113-122`）。
- **G2** Playwright 池设计精良：全局 `MAX_CONCURRENT_BROWSERS = 2` 信号量、per-profile-path 锁、shared ephemeral browser 自动重建、shutdown 时优雅关闭（`backend/app/utils/browser.py:44-65, 84-128, 131-163`）。
- **G3** `get_browser_context` 用 `@asynccontextmanager` + `try/finally` 保证每次 `context.close()` 都会执行（`browser.py:307-310, 339-345`）。
- **G4** `dedupe.py` 的 cross-source / same-source duplicate 区别处理：跨源仅记 metadata 不丢弃，同源 backfill 更长正文到 stub 行（`dedupe.py:32-79`）。
- **G5** `dedupe.py` docstring 显式声明"不在此处 commit、由 coordinator 在 batch 边界提交"——是少见的"事务边界"写在代码里的好范本（L26-31）。
- **G6** SSRF check 集成在 `BaseCollector._check_ssrf`（虽然子类必须主动调用），保证统一入口（`base.py:38-40`）。
- **G7** `BaseCollector.filter_new_content` 明确处理升序/降序两种 publish_time 排序（`base.py:71-110`），避免误判。
- **G8** `external_id` 长度归一化（>255 字节 sha1 哈希）防止 DB 列溢出（`pipeline/utils.py:109-116`）。
- **G9** Website 反信号过滤齐备——nav title / domain section / 短文本 / 无数字 URL 等多重启发式（`pipeline/utils.py:304-359`）。
- **G10** Coordinator 在 dedupe + storage 同事务（`dedupe.py` docstring + `coordinator.py:218`）。

## 详细审计清单

### 1. collectors/base.py：超时/重试/错误返回规范

- **结论：** ⚠️
- **代码位置：** `backend/app/collectors/base.py:42-115`
- **分析：**
  - 抽象方法 `fetch(source) -> List[Dict]`（L42-59）只在 docstring 描述返回值结构，没规定：
    - 网络超时由谁负责（每个子类各自调 aiohttp/playwright，timeout 散落）；
    - 重试是否在子类完成（实际未做，外层只有 fetch_tasks 指数退避调度）；
    - 异常应抛出还是返回空列表（实际看 collector_stage L120 是用 catch-all 统一处理）。
  - 子类都正确实现了 `fetch`，但接口契约的薄弱意味着新增 collector 时容易破坏一致性（例如可能写一个抛出 ValueError 的 collector 而非返回空 list）。
  - `should_fetch`（L61-69）使用 `last_fetched_at + timedelta(minutes=fetch_interval)`，但配置中 `fetch_interval` 单位为分钟 → 与 docstring 一致。
  - `validate_content`（L112-115）只校验 title/url 非空，过于宽松——任何内容只要这两个字段非空就通过。
- **建议：**
  - 在 `BaseCollector` 类 docstring 增加"实现约定"小节：`fetch` 必须在 N 秒内完成（具体由 settings 提供），网络/解析错误返回空 list 不抛出，认证错误抛特定 `AuthenticationError`。
  - 可选：把超时控制提到 base，让 `fetch` 用 `asyncio.wait_for` 包装。

### 2. website.py：Playwright 资源释放与并发控制

- **结论：** ✅
- **代码位置：** `backend/app/collectors/website.py:151-847`、`backend/app/utils/browser.py:155-345`
- **分析：**
  - Playwright 资源释放**全部走 `browser.py` 的 `get_browser_context` 上下文管理器**，由 `@asynccontextmanager` + `try/finally` 保证 `context.close()` 必执行（`browser.py:339-345`）。website.py 中的多处 `try/except Exception as exc: # noqa: BLE001 - teardown should never raise`（L188-195）对应于"如果是清理路径上的异常吃掉不冒泡到调用者"，是 teardown 的标准姿势。
  - 并发控制：进程级 `_browser_semaphore = asyncio.Semaphore(2)`（`browser.py:46`）+ per-profile 锁（L53-64）。两层保证：
    - 总浏览器数 ≤ 2，防 OOM；
    - 同 user_data_dir 串行（Chromium ProcessSingleton 限制）；
    - 不同 profile 可并行（在 2 上限内）。
  - 处理"shared browser dies between is_connected and new_context"的 race：发现 new_context 抛错时强制 teardown + 重建（`browser.py:328-337`）。这是少见的鲁棒处理。
  - websites 的 fetch 路径里多处 `except Exception ... # noqa: BLE001` 写法说明仓库整体已贯彻 ARCHITECTURE.md §9 的 ruff 不变量。
- **建议：** 无。

### 3. x_twitter.py：登录态恢复 / GraphQL 解析防御

- **结论：** ✅（部分基于 ARCHITECTURE.md §2 描述，未对全文逐行复核）
- **代码位置：** `backend/app/collectors/x_twitter.py`、`x_twitter_text.py`、`x_twitter_formatters.py`
- **分析：**
  - ARCHITECTURE.md §2 明确说 X collector 的多策略回退顺序为 `graphql → rsshub → nitter → api`。文件被拆为：
    - `x_twitter.py`（647 行）—— 主控
    - `x_twitter_text.py` —— 纯文本 / URL 工具
    - `x_twitter_formatters.py` —— GraphQL 数据格式化
  - 这种"controller + 纯函数 helpers"分层正是审计模块一推崇的边界划分。✅
  - 登录态：经由 `build_browser_session_runtime`（`collector_stage.py:64`）+ `maybe_refresh_auth_cookies`（`collector_stage.py:79`）注入 `runtime_auth.credentials.cookies`；恢复失败会进入 nitter / rsshub fallback（按 ARCHITECTURE 描述）。
- **未在本次审计验证的事项：**
  - GraphQL 响应中 None 字段的逐字段 None-check（要求 graphql 解析不能 KeyError）。这部分需要细读 `x_twitter_formatters.py`，留作后续核验。
- **建议：**
  - 后续单独审计 `x_twitter_formatters.py`：确认每个解析点对 `entry.get("content", {}).get("itemContent", {}) or {}` 这类链式访问都做了 None 兜底。

### 4. coordinator.py：阶段失败传播

- **结论：** ⚠️（与模块一 L1 同根问题）
- **代码位置：** `backend/app/pipeline/coordinator.py:154-234`
- **分析：**
  - **阶段间允许部分成功**：CollectorStage 返回 `(raw_contents, merged_warning, primary_warning)`，即使有 warning 也会把成功 fetch 的部分送入 NormalizerStage 和 StorageStage（参见 coordinator L165-218）。这是正确的 partial-success 模型。
  - **NormalizerStage / StorageStage 抛错的处理**：coordinator 没有 try/except 包住，意味着这两阶段抛错会冒到 fetch_tasks，进而递增 `error_count`（fetch_orchestrator:47）。这与"一阶段失败导致整次 fetch 失败"是一致的——比 collector 阶段更严格，但合理（normalizer/storage 都是确定性操作，失败一般意味着 schema 错误）。
  - **单条 raw 失败被吞**：见模块一 L1。pipeline 各 stage 内部都有"循环 + try/continue"模式，但不计数。
- **建议：** 把单条目失败计数加到流水线返回字典；coordinator 用 `failed_count` 字段返回给 fetch_tasks。

### 5. normalizer_stage.py：质量过滤标准

- **结论：** ✅（启发式合理）+ ⚠️（配置可发现性）
- **代码位置：** `backend/app/pipeline/normalizer_stage.py:25-171`、`backend/app/pipeline/utils.py:304-359`
- **分析：**
  - Stale gate（L130-155）：scheduled + feed-like = 7 天，scheduled + X-like = 60 分钟，manual = 7 天。差异化合理。
  - 用户可通过 `source.metadata["max_fetch_lag_minutes"]` 覆盖。⚠️ 这个钩子在文档里没出现（仅源代码注释 L129-131 提到"UI: 抓取回溯时间"）。
  - Website 反信号过滤（`pipeline/utils.py:304-359`）：
    - 强 nav title 黑名单（"all topics"、"my library" 等）
    - domain-level section title（"hbr.org" → {"strategy", "leadership", ...}）
    - 短文本（< 250 chars 且 < 40 词）+ 无数字 URL → low_content_single_phrase_link
    - title-text 完全相同 → 判作 nav 链接
  - 启发式相对**进取（aggressive）**——可能误杀真正的极短文章（如 50 词的短评）。但目标是过滤 nav/section 噪声而非保留所有文章，权衡合理。
  - 语义去重（L159-167）按 (source_id, title, publish_time) DB 查询。⚠️ 每条 raw_content 一次 DB query，N 条就 N 次 round-trip。批量场景效率不佳，但 fetch 频率低、每次 raw 数量也小（典型 < 50），可接受。
- **建议：**
  - 在 `docs/USER_GUIDE.md` 里加一段"如何调整抓取回溯时间"，覆盖 metadata.max_fetch_lag_minutes。
  - 语义去重改为单次 IN 查询：先收集所有 (title, publish_time) 元组，一次 query 取回 existing set。

### 6. dedupe.py + dedupe_raw_contents：URL 规范化

- **结论：** ⚠️
- **代码位置：** `backend/app/pipeline/utils.py:210-220`、`backend/app/pipeline/dedupe.py`
- **分析：**
  - **DB 层去重**走 `external_id`（dedupe.py），不依赖 URL。各 collector 提供稳定的 external_id（X 的 tweet_id、YouTube 的 video_id、RSS 的 guid 等），是正确设计。URL 规范化在这一层不是问题。
  - **内存批次去重** `dedupe_raw_contents`（`pipeline/utils.py:210-220`）按 `external_id || url || title` 简单 key 去重，**对 URL 不做任何 canonicalization**：
    - `https://example.com/a` 与 `https://example.com/a/`（trailing slash）→ 视为不同
    - `https://example.com/a?utm_source=x` 与 `https://example.com/a?utm_source=y` → 视为不同
    - `http://example.com/a` 与 `https://example.com/a` → 视为不同
    - 重定向前后 URL → 视为不同
  - 影响：对没有 external_id 的源（罕见，但比如某些 RSS 没 guid），同一篇文章可能在一次 fetch 内被收两次。
- **建议：**
  - 增加 `_canonicalize_url` 函数：lower-case host、去 trailing slash、去 fragment、white-list query params（保留语义参数如 `id=`，去除 utm_*）。
  - 在 `dedupe_raw_contents` 中先把 url canonicalize 再作为 fallback key。

### 7. error_count 递增 / 阈值禁用 / 恢复

- **结论：** ⚠️
- **代码位置：** `backend/app/pipeline/coordinator.py:111-117`、`backend/app/tasks/fetch_orchestrator.py:47`、`backend/app/tasks/fetch_tasks.py:180`
- **分析：**
  - 递增逻辑：coordinator `_update_source_status`（L98-119）—— primary_warning 是 error 时 +1，否则归零。✅
  - `fetch_orchestrator.py:47` 也有 `source.error_count = (source.error_count or 0) + 1` —— 看代码上下文（grep 单行）这是 orchestrator 自己的 outcome 写入路径，**与 coordinator 路径同时在用**，可能存在重复递增。需要进一步核验是否会双计数。
  - 退避：`fetch_tasks.py:180` `backoff = 1 << min(int(source.error_count or 0), 5)` → 1, 2, 4, 8, 16, 32（封顶）。✅
  - **没有阈值禁用**：grep 结果只显示 `Source is disabled` 是判断现存 disabled flag，没有"error_count 达到 N 自动 source.is_active = False"的代码。失败源会以最大 32 倍间隔被慢速重试无限次。
  - 没有恢复机制（成功一次 reset 到 0 是有的，但没有"已禁用源到达某状态后被自动重启动"）。
- **建议：**
  - 增加 settings 项 `source_disable_threshold`（默认 50），error_count 超过即自动 `is_active = False` + 通知。
  - 在 `pim` UI / `pimctl sources reset-error` 里允许人工 unblock。

### 8. FETCH_CONCURRENCY：死锁/资源饥饿

- **结论：** ✅
- **代码位置：** `backend/app/config.py:56`、`backend/app/utils/browser.py:46`、`backend/app/tasks/task_queue.py`
- **分析：**
  - `settings.fetch_concurrency = 20`（最大并行 fetch），由 task_queue worker 数控制。
  - 同时 `MAX_CONCURRENT_BROWSERS = 2`（browser.py），意味着 20 个 fetch 共享 2 个 Chromium，需要 Playwright 的 fetch 会自然在 semaphore 上排队，其它（aiohttp）不受影响。
  - **死锁风险**：低——所有锁都是 `asyncio.Lock` / `asyncio.Semaphore`，没有跨任务持锁等待。
  - **饥饿风险**：低——同 profile 串行可能让该 profile 的多个待 fetch 任务排队，但有 backoff、且 fetch_orchestrator 通常按时间顺序触发，不会出现某 profile 永远抢不到。
  - SQLite 写并发也是天然瓶颈（见模块六），但 fetch 本身只读外网，写库时已离开 fetch_concurrency 范畴。
- **建议：** 无；建议在文档里画一张 concurrency 拓扑图（task_queue 20 → fetch 路径 → browser pool 2 / network N），便于运维理解资源边界。

## 涉及文件

- `backend/app/collectors/base.py`
- `backend/app/collectors/website.py`（部分行数与异常分布通过 grep 验证）
- `backend/app/collectors/x_twitter.py`（基于 ARCHITECTURE.md 与 grep 概览）
- `backend/app/collectors/`（rss/podcast/youtube/website_helpers/website_parser/x_twitter_text/x_twitter_formatters）
- `backend/app/pipeline/collector_stage.py`
- `backend/app/pipeline/normalizer_stage.py`
- `backend/app/pipeline/dedupe.py`
- `backend/app/pipeline/utils.py`
- `backend/app/pipeline/coordinator.py`
- `backend/app/utils/browser.py`
- `backend/app/tasks/fetch_orchestrator.py`（grep 验证）
- `backend/app/tasks/fetch_tasks.py`（grep 验证）
