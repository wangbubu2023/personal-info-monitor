# 模块四：AI 处理与摘要 审计报告

## 总评

PIM 的 AI 链路已经做了**关键的反脆弱设计**：
- fetch 主路径明确**不调用 LLM**（`content_processor.py:174` 注释 + 实现），让 AI 延迟与可用性不影响抓取吞吐；
- 关键词匹配用了非常完整的 ReDoS 防护（pattern 长度限制 + AST 风格的不安全模式黑名单 + SIGALRM 超时 + 输入截断）；
- Reader 流式翻译用 NDJSON 帧 + 每段独立超时 + 成功率阈值（0.45）+ 缓存写入兜底，工程姿态成熟；
- Hourly Digest LLM 选稿失败时回退到本地 RankingService。

主要问题：（1）`settings.ai_processing_enabled` 这个旗标实际上**只在启动横幅打印里被读取**，没有任何 AI 调用路径会因它为 false 而跳过——是一个 dead config；（2）摘要 / 翻译的 token 上限和文本截断分散在 Translator/Summarizer 内部，缺少在 ContentProcessor 层的统一闸门；（3）Reader streaming 没有在循环内显式监听 client cancellation，依赖 Starlette 的 generator cleanup。

## 严重问题（❌）

无严重问题。

## 轻微问题（⚠️）

- **L1** `Settings.ai_processing_enabled`（`backend/app/config.py:95`）只在启动横幅打印（`main.py:116`），全代码无其他读取——是 dead flag。
- **L2** Translator/Summarizer 的 cloud fallback 链通过 system_settings 中多个键散落配置（`summarization_fallback_enabled`、`summarization_cloud_fallback_enabled`、`translation_fallback_enabled`、`translation_cloud_fallback_enabled`），新旧键并存，命名不统一（`backend/app/processors/summarizer.py:11-50`、`translator.py:34-64`）。
- **L3** `selection.py` LLM 选稿超时 75s + max_tokens 800 是显式上限，但**输入端 catalog 长度无截断**（`build_selection_catalog` 直接拼所有 entries）——大池子时 prompt 可超 LLM 上下文（`selection.py:23-35`）。
- **L4** `streaming.py` 没在循环里显式 `await request.is_disconnected()`，client 提前断开后下一段仍会发起翻译请求（不消耗大量算力但仍浪费 1 段时间）（`streaming.py:144-171`）。
- **L5** `keyword_matcher._safe_regex_search` 在工作线程中只能依赖 16k 字符截断（无 SIGALRM）；这放宽了 ReDoS 防护但符合"main thread/Unix 才能用 alarm"的限制（`keyword_matcher.py:160-192`）。
- **L6** AI 成本：没有"每小时/每天 token 上限"的硬开关；只能依赖 max_tokens 和单请求超时被动控制；缺乏意外天价账单的护栏。

## 良好实践（✅）

- **G1** Fetch 主路径**不发起 LLM 调用**（`content_processor.py:174-177` 显式注释 + summarize/translate 仅在 reprocess_content 中调用），保障抓取吞吐与 AI 可用性解耦。
- **G2** ReDoS 防护齐备：256 字符 pattern 长度上限、四类不安全 pattern 黑名单（backreference、lookbehind、嵌套 / 连续 quantifier）、SIGALRM 2s 超时、非主线程 fallback 截断 16k 字符（`keyword_matcher.py:11-25, 141-192`）。
- **G3** Reader streaming 用 NDJSON 帧，每段独立 22s 超时，部分失败回退原文，成功率 ≥ 0.45 才写缓存（`streaming.py:78-205`）。
- **G4** Hourly Digest 选稿在 LLM 输出 malformed 时**自动回退到 RankingService**（`selection.py:38-78, 81-93`），双轨保障。
- **G5** LLM 输出解析 tolerant：去 markdown 围栏、提取 `{}` 块、对未知 ID 静默丢弃（`selection.py:38-78`）。
- **G6** Cookie full-text fetch 受 SSRF + cookie-host 双重检查保护（`content_processor.py:96-99`），不会跨主机泄漏 cookie。
- **G7** `wrapper URL` 检测：news.google.com/rss/articles/* 这种重定向器在 cookie fetch 阶段被显式短路（`content_processor.py:78-86, 92`）。
- **G8** Strategy registry：`_CONTENT_TYPE_STRATEGIES` 把 per-content-type 旋钮（summary 字符上限、是否启用 cookie fulltext）抽到一个表，避免 if/elif 链（`content_processor.py:44-57`）。
- **G9** features.py 显式记录 ADR-003 衍生的"X Playwright 需运营人员主动开启"决策（`features.py:40-47`），与启动期警告联动（`main.py:145-150`）。

## 详细审计清单

### 1. content_processor.py：AI_PROCESSING_ENABLED=false 时是否完全跳过

- **结论：** ❌（不是按预期工作的）→ 建议降级为 ⚠️（实际危害低，但配置失实）
- **代码位置：** `backend/app/config.py:95`、`backend/app/main.py:116`、`backend/app/processors/content_processor.py:1-310`
- **分析：**
  - `settings.ai_processing_enabled` 在 config.py 定义（默认 False），但**整个仓库只在 `main.py:116` 的启动横幅打印里被读取**，没有任何代码路径用它来跳过 AI 调用。
  - 实际 AI 调用的"开关"是分散的：
    - 摘要/翻译只在 `reprocess_content`（`content_processor.py:279-310`）和 reader 端点中显式调用；fetch 路径（`process` 函数 L134-233）已经被 hardcode 为"不调用 LLM"。
    - 多提供商 fallback 通过 `system_settings` 中 `summarization_fallback_enabled` / `translation_fallback_enabled` 控制，与全局 `ai_processing_enabled` 无关联。
  - 实际上**用户把 `AI_PROCESSING_ENABLED=true` 设进 .env 不会让 fetch 自动产出 AI 摘要**——他们仍需要触发 reprocess 或 reader 翻译。
  - 这是文档/配置层失实，不是行为缺陷（fetch 路径不调 LLM 反而是好事）。
- **建议：**
  - 要么删除 `Settings.ai_processing_enabled` + 对应启动打印，要么把它真正接入 ContentProcessor 用作"批量后处理是否启用"的开关。前者改动最小、最诚实。

### 2. summarizer.py：超时 / 重试 / 降级 / Token 上限

- **结论：** ⚠️
- **代码位置：** `backend/app/processors/summarizer.py:1-100+`
- **分析（基于已读前 100 行 + 引用面）：**
  - Cloud fallback 配置走 system_settings 中的 `summarization_fallback`（含 provider、model、api_base、api_key）。`get_summarization_fallback_model_settings` 在 fallback 标志关时返回 `{}`，调用方应据此关闭 fallback。
  - 客户端按 (api_key, api_base) tuple 缓存（L57-59），避免每次重建 OpenAI client。
  - **未在本次审计验证：** 摘要超时（API call timeout）、重试次数、过长文本截断逻辑——需进一步看 summarizer.py 后半部分。基于业界默认（OpenAI SDK 默认 600s）这通常是问题。
  - **降级链：** 主模型调用失败 → fallback 模型调用 → 最终失败时返回 None / 原文。具体回退链路在文件后半段。
- **建议：**
  - 后续单独审计 `summarizer.py` 后 300 行：确认 (a) 主调用 timeout 显式 ≤ 60s；(b) 重试次数有上限；(c) 超长 input 触发截断而非 422 错误返回；(d) fallback 失败时返回原文 / None，而非抛错让上层炸掉。

### 3. translator.py：多提供商 fallback 链

- **结论：** ⚠️（结构合理，命名混乱）
- **代码位置：** `backend/app/processors/translator.py:1-100+`
- **分析：**
  - 抽象 `ModelProviderClient`（`app.ai.provider`）+ `ModelRuntime` 是统一入口，list_ollama_models 等表明支持本地 Ollama。✅
  - `get_translation_settings` → `enrich_model_settings_from_api_config` 把 system_settings 与 api_configs（模型接入凭据库）合并，得到完整 runtime config。✅
  - **命名问题：** `is_translation_cloud_fallback_enabled` 与 `is_translation_fallback_enabled`（后者只是前者的 alias for "patch compatibility"），同时 system_settings 中也有 `translation_fallback_enabled` 与 `translation_cloud_fallback_enabled` 两个键并存。新旧键迁移没完成。
  - Translator 用法：`Translator()` 实例化，`translate(text, "zh-CN")` 异步调用。fallback 链在文件后半段（`get_translation_cloud_fallback_openai_settings` 等）。
- **建议：**
  - 把"cloud_fallback" 与 "fallback" 统一到一个 key，写一个迁移使旧 key 显式 deprecated 并在启动期 logger.warning。
  - 后续单独审计 translator.py 后 300 行：确认主→fallback 切换的具体触发条件（是 timeout 还是 5xx？）。

### 4. keyword_matcher.py：ReDoS 防护

- **结论：** ✅
- **代码位置：** `backend/app/processors/keyword_matcher.py:11-25, 141-192`
- **分析：**
  - 静态防护：
    - `MAX_REGEX_LENGTH = 256`，超长直接拒。
    - `_UNSAFE_REGEX_PATTERNS`：四类被禁用的模式（backreference、lookbehind、嵌套 quantifier、连续 quantifier）。这覆盖了 catastrophic backtracking 的主要构造。
    - 任何 `re.error` 也会被拒。
  - 动态防护（`_safe_regex_search`）：
    - 主线程 + Unix（有 SIGALRM）：`signal.alarm(2)` 设 2 秒硬超时；
    - 非主线程（worker thread）/ Windows：截断输入到 16,000 字符。
  - 等效词扩展（`_keyword_terms` L100-105）通过 `dedupe_keywords_case_insensitive` 去重；不存在递归扩展，**没有环路风险**。
  - exact 匹配单独构造 `\b...\b` word boundary（仅当 candidate 含字母数字/下划线时），CJK 关键词不强制 word boundary——这是合理的语言学决策。
- **建议：** 无；如果需要再硬一点，可以引入 `regex` 库（支持 timeout 参数），消除对 SIGALRM 的依赖。

### 5. hourly_digest/selection.py：内容选择算法多样性

- **结论：** ⚠️
- **代码位置：** `backend/app/services/hourly_digest/selection.py:1-129`
- **分析：**
  - 流程：(a) `build_selection_catalog` 把所有候选展平成"content_id=... 来源=... 标题=... 摘要=..."文本；(b) LLM prompt 要求"按重要性降序输出 ids 数组"；(c) 解析；(d) 解析失败时 `fallback_pick_ids_from_ranking` 用 `RankingService.cluster_and_rank` 选取。
  - **多样性保障：** 仅靠 prompt 提示"按重要性降序"。代码里**没有对 source 维度做配额或最小覆盖率**约束。如果某一时段全部 30 条来自同一个源（例如 X 高产用户），LLM 大概率把它们都选进去。
  - 摘要长度：每条候选的摘要被截到 280 字符（L32-33），合理。
  - **catalog 总长度无上限**：候选很多时整个 prompt 会很长，可能撞上下文窗口。max_tokens=800 是输出上限，但输入侧没保护。
  - 解析层 tolerant，且有 fallback to ranking_service。✅
- **建议：**
  - 在 `build_selection_catalog` 加 `max_entries`（默认 60）参数，超过则按预排序截断。
  - 在 prompt 中加一句"至多 N 条来自同一个 source"，或者改为 cluster-then-pick：先按 source 分桶，每桶选 top-1，再 LLM 排序。

### 6. streaming.py：SSE/NDJSON 客户端断开与资源清理

- **结论：** ⚠️
- **代码位置：** `backend/app/services/reader/streaming.py:78-205`
- **分析：**
  - 流程清晰：init → cached fast path → 否则逐段翻译 → done。
  - 翻译失败时 `partial_fallback=True` + `message="部分段落翻译失败，已回退原文"`，体验友好。✅
  - 缓存只在 `translated_success` 时写入，避免污染缓存（L184-195）。✅
  - **客户端断开：** 循环 L144-171 没有 `await request.is_disconnected()` 检查；如果 client 在第 5 段时关闭连接，第 6/7/... 段仍会发起翻译请求，每段最长 22s。Starlette 会在 client 关闭后取消 generator（`yield` 时抛 CancelledError），所以最多浪费 1 段翻译时间，**不是资源泄漏**，但是浪费配额。
  - `Translator` 实例在每次调用都新建（L134）；按上面 summarizer 的实现，Translator 内部缓存 client 是按进程级（self.client），不会反复重建底层连接，OK。
  - 没有 `finally` 块——Python AsyncGenerator 在被 close 时会从 `yield` 处抛 GeneratorExit，能保证局部变量被回收，但**没有显式 cleanup hook**。如果未来增加占用资源的对象（例如临时文件 / DB 长事务），需要加 try/finally。
- **建议：**
  - 在循环开头加 `if await request.is_disconnected(): return`（需要把 request 对象传入 emit_reader_translation）。
  - 在主流程外包 try/finally，保留为未来扩展资源清理留 hook。

### 7. AI 成本控制

- **结论：** ⚠️
- **代码位置：** 散落（`processors/summarizer.py`、`processors/translator.py`、`services/hourly_digest/selection.py`、`services/reader/streaming.py`）
- **分析：**
  - 现有控制：
    - 每段翻译 22s 超时；
    - 选稿 max_tokens=800；
    - keyword matcher 输入截断（16k）；
    - reader 段落 < 5 字符跳过翻译；
    - `truncate_content` 在 ContentProcessor 中限制 full_content 长度。
  - 没有的护栏：
    - **每小时/每天 token 总额上限**——一次大批量 reprocess 可能在用户不察觉的情况下烧掉数十美元；
    - **逐 source 每日翻译次数限制**——某个 source 异常吐出 1000 条新内容时会立即引发批量翻译；
    - **token-aware 文本截断**——summarizer 按字符截断，没考虑 tokenizer。
- **建议：**
  - 引入 `settings.ai_daily_token_budget`（默认 100k tokens）+ 一个 `app/utils/ai_budget.py` 累计模块（持久到 SQLite）。每次 LLM 调用前先检查预算。
  - reader 的"重新翻译"按钮在前端 throttle（已有 React Query staleTime，建议提到 5 分钟）。

## 涉及文件

- `backend/app/processors/content_processor.py`
- `backend/app/processors/summarizer.py`（前 100 行 + grep 验证）
- `backend/app/processors/translator.py`（前 100 行）
- `backend/app/processors/keyword_matcher.py`
- `backend/app/services/hourly_digest/selection.py`
- `backend/app/services/reader/streaming.py`
- `backend/app/features.py`
- `backend/app/config.py`（ai_processing_enabled 验证）
- `backend/app/main.py`（grep 验证唯一引用）

## 后续待审计的细节

- `summarizer.py` 后 300 行：超时、重试、token 截断、fallback 链终态。
- `translator.py` 后 300 行：多提供商切换条件、错误归类、本地 Ollama 路径。
- `app/ai/provider.py`：`ModelProviderClient.generate_text` 的统一超时/重试约定。
