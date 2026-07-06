# PIM Review Verification And Construction Tracker

**日期：** 2026-07-02（更新：2026-07-06，同步审查后代改项：T5.1 dead-code 预算门禁、RSS 死代码删除与每周体检邮件已按当前工作树核验）

**输入文档：**
- `2026-07-02-pim-expert-review-report.md`
- `2026-07-02-pim-improvement-plan.md`

**目的：** 将两份文档中的修复/改进点逐项映射到当前代码状态，给出验证结论，并形成后续施工顺序与验收口径。

## 0. 状态图例

| 状态 | 含义 |
|---|---|
| ✅ 已完成 | 当前代码已实现，且有测试或静态证据支撑。 |
| 🟡 部分完成 | 已覆盖核心场景，但同类路径、边界或生产接线仍不完整。 |
| ❌ 未完成 | 当前代码未实现或仅有死代码/测试孤岛。 |
| 🔬 需实测 | 静态代码可判断方向，但必须用真实信源/运行环境验证。 |
| ⏸ 暂缓 | 不建议在当前阶段施工，需评测数据或产品决策。 |

## 1. 总体验证结论

| 类别 | 结论 |
|---|---|
| 已完成的最高优先级问题 | P1-2 静默失败、P1-3 RSS 薄内容误丢、P1-4 日期数字段误合并、P1-5 URL 归一化已完成；P1-1 RSS 源二跳已从 collector 前置移除。 |
| 仍未完成的关键风险 | T0.1 500 条人工标注集、T3.4 embedding 决策门、VPS/付费墙/X cookie 真实端到端实测仍未完成；T0.1 生产候选导出脚本已可从近 30 天内容生成标注 JSONL，并支持 `--min-records/--expand-days-step/--max-days` 在不足时自动扩大时间窗口，本地当前 `--limit 500 --days 30 --min-records 500 --max-days 365` 自动扩到 60 天并导出 500 条/76 源；新增 `prelabel_eval_candidates.py` 可为候选集补 `suggested_label/suggested_confidence/suggested_reason/review_priority`，本地 500 条候选预标为 must_see 37、ok 351、noise 112，正式 `label` 仍保持空值等待人工确认；新增 `review_eval_candidates.py` 可把预标候选导出为人工审核 TSV 或单文件 HTML 审核页、将填好的 TSV 安全回填为正式 label，并用 `status --require-complete` 检查审核进度/坏标签/缺行，本地已导出 `/tmp/pim_eval_candidates_500_review.tsv`（表头 + 500 行）和 `/tmp/pim_eval_candidates_500_review.html`（500 条浏览器审核页，高优先级 204 条），当前 status 显示 labeled=0、remaining_unlabeled=500；标注结果校验/安装脚本已能强制检查 500 条、合法标签、唯一 ID 和来源覆盖，history gate 已可检查 ≥4 个历史点与 `precision@20` 不降，当前候选集只剩 500 条缺正式 label，仍需人工审核建议并跑真实历史；T0.3 已生成真实 20 源 dry-run 表，36kr/Engadget 已复核为重复导致的低 would-store，Lex Fridman 空结果已修为 YouTube RSS 优先路径，CNN fallback 覆盖率已从 1 条修复到 30 collector/29 would-store，仍剩 Reuters 登录墙等实测发现。 |
| 测试状态 | 最近一次完整验证：后端 `1498 passed`；后端 ruff `All checks passed`；Phase 7 架构边界检查 clean；BLE001 budget `189 <= 189`；dead-code budget `415 <= 415`；前端 `107 passed`；前端 lint/build 均通过。本轮增量验证覆盖 website collector、排序/RSS/Podcast/listing translation/process/acceptance、title-only acceptance、slug 放宽、T2.2 canonical/publish-time 回填、P1-5/T2.1 历史 canonical external_id 回填脚本、T2.3 title identity 生产写入、T3.3 hourly digest event items、T4.2 score vocab YAML reload、T4.3 score feedback event timeline、P2-6 fetch 孤岛删除、T5.1/T5.4 RankingService/DigestService/DoctorService/MonitorService/ProbeService/probe_strategies/api_config_credentials/ContentProcessor/CollectorStage/Coordinator/keyword_rules 收编、RSS hydration 死代码删除、dead-code 预算门禁与每周体检邮件（含 offline eval history 趋势）、processor/X collector/pipeline/services canonical import 与 fetch→ingest 静态边界收敛、T0.1 生产候选导出/预标建议/人工审核 TSV 与 HTML 导出回填/status 进度门禁/标注校验/历史护栏脚本，以及 T0.3 20 源 field-test 脚本和真实 dry-run 报告。 |
| 当前施工策略 | 继续优先做“失败可见、去重正确、调度不漏、可观测性真实”四类底层修复；算法/排序/embedding 类改动先依赖离线评测集。 |

## 2. 审阅报告 P1/P2 问题逐项核验

### P1

| 编号 | 问题 | 当前结论 | 当前证据 | 后续施工 |
|---|---|---|---|---|
| P1-1 | RSS 每轮对全部 entry 去重前二跳抓全文 | ✅ 已完成 | `RSSCollector.fetch()` 已改为只解析 `_parse_entry`，测试 `test_rss_fetch_issues_no_page_requests_before_dedupe` 在网络边界（`fetch_public_http_text`）锁定 RSS fetch 阶段零文章页请求；`WebsiteCollector._known_duplicate_external_id()` 会在 RSS/listing/direct hydrate 前跳过与 `source.last_content_id` 匹配的已知条目；新增 `_known_existing_content_indexes()` 在 hydrate 前批量查询同源已入库 identity（external_id/original_url/canonical metadata），非 latest 旧条目也会跳过二跳。测试覆盖 latest marker 与同源旧条目跳过、新条目仍 hydrate；rss.py 内遗留的 hydration 死代码已全部删除（见 T5.1）。 | 后续用真实 feed 统计稳态外呼次数。 |
| P1-2 | collector 吞异常变成假 no_new_content | ✅ 已完成 | RSS/YouTube/X/website static catch-all 已改抛 `FetchFailureError(classify_exception(exc))`；X 全策略空结果抛 unknown；已有测试覆盖 X 全空、YouTube 异常。 | 补一条 pipeline 级集成测试：collector 全失败后 source.error_count 递增、cooldown 生效。 |
| P1-3 | RSS <100 字条目被 collector 丢弃 | ✅ 已完成 | RSS `validate_content` 只校验 title/url 与 binary-looking body；短摘要测试已改为接受；`authority_type=regulator/official` 的 website/rss title-only 公告可放行，并写 `acceptance_relaxed`。 | 后续需真实监管公告源实测 Dashboard 可见性。 |
| P1-4 | URL canonical 化把 8 位日期段当文章 ID | ✅ 已完成 | `app/utils/url.py` 增加 `_DATE_YYYYMMDD_RE`，测试覆盖 `/news/20260630/a` 与 `/b` 不合并。 | 无。 |
| P1-5 | URL 去重不剥 utm/query、不并 http/https | ✅ 已完成 | `normalize_source_url_for_dedupe` 统一 https、剥 `www.`、剥 tracking query/fragment、处理 `/amp` 尾缀和 `amp.` 子域；测试覆盖 utm/fbclid/from/http↔https/AMP。新增 `scripts/backfill_canonical_external_ids.py` 可 dry-run/commit 近 30 天历史 canonical external_id，并对同源冲突只报告不覆盖。 | 生产执行前先 dry-run 审核 conflict 数。 |

### P2

| 编号 | 问题 | 当前结论 | 当前证据 | 后续施工 |
|---|---|---|---|---|
| P2-6 | `fetch_source_batch` 死代码，真实主链在 canonical fetch domain | ✅ 已完成 | 已删除 `app.domains.fetch.orchestrator.fetch_source_batch`、`app.domains.fetch` re-export、孤岛测试 `test_fetch_orchestrator.py` 与未接线的 `FetchBatch/FetchRequest/RawItem` DTO 模块；`docs/ARCHITECTURE.md` / `docs/PROJECT_STRUCTURE.md` 改为承认真实主链 `tasks.fetch_tasks -> domains.fetch.coordinator -> domains.fetch.collector_stage -> domains/fetch/collectors`。`rg "fetch_source_batch|FetchBatch|FetchRequest|RawItem|FetchWarning" backend/app backend/tests` 不再命中生产/测试代码。 | 无。 |
| P2-7 | `session_health.py` 未接线 | ✅ 已完成 | website hydration 登录/墙失败会写 `metadata_.session_health`；X GraphQL cookie 缺失/过期/异常也会写 session health；`serialize_source` 透出顶层 `session_health`。测试覆盖 website hydration、X no cookies/expired、API serialization。 | 后续需真实站点实测 bot wall/captcha 文案分类准确率。 |
| P2-8 | 自动发现 feed URL 不持久化 | ✅ 已完成 | `WebsiteCollector.fetch()` 在 RSS discover 成功后调用 `persist_discovered_feed(source, feed_url)`；`test_website_discovered_feed_is_persisted` 覆盖自动链路。 | 无。 |
| P2-9 | fetch_profile fulltext/preferred_strategy 恒空 | ✅ 已完成 | `run_fetch_pipeline` 聚合本批 `fulltext_status/full_content/article_fulltext` 并传入 `record_fetch_result`，同时推断 `preferred_strategy`；`test_run_fetch_pipeline_records_fulltext_profile_fields` 覆盖主链。 | 后续可把策略粒度从 `rss/article_hydration/source_type` 细化到具体 collector。 |
| P2-10 | finish_content 用 LLM semaphore 包裹非 LLM 工作 | ✅ 已完成 | `finish_content()` 使用 `get_finalize_semaphore()` 包住 finalize 主流程，`get_llm_semaphore()` 保留给真正 LLM 路径和兼容测试 patch target。 | 后续可为 summarizer/translator 单独加更细的预算指标。 |
| P2-11 | 重启丢 process 队列任务，无补投 | ✅ 已完成 | `enqueue_unfinished_content_on_startup()` 扫描近 24h `fetch_acceptance is None` 内容并 enqueue `ingest_finish`；lifespan 启动后调用。 | 可补生产指标观察补投数量。 |
| P2-12 | discovery 域名比较 `lstrip("www.")` 误用 | ✅ 已完成 | `_host()` 已改为 `.removeprefix("www.")`。 | 无。 |
| P2-13 | X 等非 feed 源默认 freshness 窗口固定 60min | ✅ 已完成 | normalizer 对非 feed 源使用 `max(fetch_interval * 2, 60)`；新增显式单测覆盖 X interval=120 时 180min 内容不 stale。 | 无。 |
| P2-14 | CollectorStage 自动绑定 auth 提前 commit | ✅ 已完成 | `collector_stage.py` 已删除 auto-bind 内部 `db.commit()` / `db.refresh()`。 | 无。 |
| P2-15 | `use_keyword_filter=true` 且无启用关键词会全拒 | ✅ 已完成 | `_apply_keyword_filter` 在无启用关键词时保留全部内容，并写 `keyword_filter_misconfigured` warning。 | 无。 |
| P2-16 | `FETCH_CONCURRENCY=20` 实际被 4 个 fetch worker 限死 | ✅ 已完成 | lifespan 启动 `task_queue.start_workers(fetch_workers=settings.fetch_concurrency, ...)`，启动横幅也打印配置值。 | 无。 |
| P2-17 | corroboration 按 source_id 计数虚增 | ✅ 已完成 | `compute_corroboration` 使用 registrable domain 计数，且同 `duplicate_group_id` 只计一次；测试覆盖同域子域不虚增与 duplicate_group 合并。T2.3 已生产写入 `duplicate_group_id`。 | 后续用离线评测抽样确认同题材误合并率。 |

## 3. 审阅报告其他改进点核验

| 主题 | 当前结论 | 说明 | 后续施工 |
|---|---|---|---|
| domains/enrich 反向依赖 services | ✅ 已完成 | `RankingService` 已迁到 `app.domains.score.ranking`，`DigestService` 已迁到 `app.domains.enrich.digest`，`DoctorService` 已迁到 `app.domains.system.doctor`，`MonitorService` 已迁到 `app.domains.sources.monitoring`，`ProbeService/probe_strategies` 已迁到 `app.domains.sources.probe`，`api_config_credentials` 已迁到 `app.platform.auth.api_config_credentials`；`ContentProcessor` 已迁到 `app.domains.ingest.content_processor`；`CollectorStage` 与 `Coordinator` 已迁到 `app.domains.fetch`；`keyword_rules` 生产调用与行为测试已迁到 `app.domains.ingest.keywords.rules`。生产代码已不再消费旧 `app.services.*` / `app.processors.*` / `app.pipeline.*` shim；旧路径只保留外部兼容 facade 与 `test_legacy_facades.py` 自测，`check_domain_imports.py --phase=7` 和 AST 边界测试防回退。 | 后续只按 dead-code budget 下调节奏继续清兼容债。 |
| 生产代码消费 shim | ✅ 已完成 | `finish.py` 已改为直连 `domains.ingest.quality_metadata` / `domains.score.scoring`；本轮将生产代码里的 `app.processors.{content_processor,extractor,keyword_matcher,summarizer,translator}`、`app.collectors.x_twitter`、`app.pipeline.{collector_stage,coordinator,utils}` 消费点切到 canonical `domains` / `platform` / `utils` 路径，并新增 AST 边界测试锁定。 | 后续只保留外部兼容 import / 测试 patch target。 |
| 质量过滤重复 | ✅ 已完成 | `website_parser` / `NormalizerStage` / `build_raw_content_objects` 不再用 `get_website_content_reject_reason` 做保存前业务拦截，只保留 `get_non_article_format_reject_reason` 过滤 gallery/slideshow/roundup 等格式性非文章；正文完整度与低信号业务 gating 统一到 finish-time `assess_fetch_acceptance`。 | 后续可删除或降级 `get_website_content_reject_reason` 的旧启发式债务。 |
| Source.metadata_ 混写 | ✅ 已完成 | `fetch_profile` 高频尝试结果已升表到 `source_fetch_log`；retry/cooldown 当前状态已升列到 `sources.fetch_failure_*` / `fetch_cooldown_until`；rss_health 最新状态已升列到 `sources.rss_health_*`；discovery 最新诊断已升列到 `sources.discovery_*`；`last_fetch_outcome` 已升列到 `sources.last_fetch_outcome_*`；`session_health/session_health_alert` 已升列到 `sources.session_health_*` / `sources.session_health_alert_*`。上述路径读写和 API 序列化均优先结构化存储并保留 metadata fallback。 | 运行态升列完成；`metadata_` 后续只保留配置、兼容投影和内容特定扩展，不再作为这些最新运行状态的权威源。 |
| SQLite JSON score 查询 | ✅ 已完成 | `contents` 新增 `article_score/final_score/selection_status/lane` 投影列和索引，Alembic `20260702_0020` 从 metadata JSON 回填；`finish_content()` 双写列；Score Lab 过滤/排序与 hourly digest candidate 排序优先走列、JSON fallback 保老数据兼容。 | 后续可逐步把其他 score 消费点从 metadata 迁到列。 |
| website canonical/og:url 回填 | ✅ 已完成 | `extract_article_page_metadata` 从 canonical/og:url/JSON-LD URL 提取 canonical；normalizer/build_content 写 `canonical_url` 与 `canonical_external_id`；dedupe identity 消费 canonical metadata。 | 后续随真实源抽样验证误合并率。 |
| website 发布时间最弱 | ✅ 已完成 | 已从现有二跳 HTML 的 JSON-LD/meta/time 提取 `datePublished`，在缺失或 estimated 时回填 `publish_time` 并标记 `publish_time_source=html_metadata`；避免有 HTML 时再逐篇额外请求。 | 后续抽样确认不同站点 date 字段覆盖率。 |
| discovery 保守档默认启用 | ✅ 已完成 | `resolve_discovery_rules()` 在无显式 `metadata.discovery` 时生成 source URL 本页的保守默认档，要求同域 + article-shaped URL，写 `discovery_diagnostics`；显式 `discovery.mode=off` / `listing_discovery=false` 可关闭，默认空结果继续 fall through 到静态抓取。测试覆盖默认规则、关闭开关、非文章 URL 诊断与 WebsiteCollector 默认接线。 | 后续用真实源跑 coverage@source。 |
| trafilatura 兜底正文抽取 | ✅ 已完成 | `ContentExtractor.extract()` 顺序为 structured_article → readability → trafilatura → BeautifulSoup；readability 稀薄/疑似局部块时会触发 trafilatura，二跳正文抽取经 `app.domains.fetch.article_body._extract_article_text()` 同样接入该 extractor。`tests/test_processors.py` 覆盖 sparse/partial/short/exception fallback。 | 后续用 T0.1 真实评测集做 A/B 阈值调优。 |
| YouTube transcript | ✅ 已完成 | `YouTubeCollector` 会从 yt-dlp 已返回的 `requested_subtitles` / `subtitles` / `automatic_captions` inline data 或 fragments 抽取 transcript，不额外下载字幕 URL；抽到 transcript 时写入 content/full_content 路径并标记 `metadata.youtube_transcript_*`、`article_fulltext=true`、`fulltext_status=full`。测试覆盖 VTT 与 fragments 两种形态。 | 后续用真实频道抽样统计字幕覆盖率；若需下载字幕 URL，再单独评估外呼成本。 |
| Podcast duration | ✅ 已完成 | RSS 解析保留 `itunes_duration`，Podcast enhancement 解析整数秒、`MM:SS`、`HH:MM:SS` 并写入 `metadata.audio_duration`；测试覆盖常见格式。 | 无。 |
| X 外链文章主体化 | ✅ 已完成 | X collector 会优先使用 `metadata.urls.expanded_url/unwound_url` 中的外站链接，在有界 `x_external_article_fetch_limit` 内复用 public article body 抽取；成功后把 X item 升级为 external article，写 `article_url/external_article_url/tweet_url/tweet_text/article_fulltext/fulltext_status`，并保留 X 长文 hydration 路径。测试覆盖普通短推 expanded_url → 外链正文主体化。 | 后续用真实 X 信源抽样确认不同短链/站点的正文抽取率。 |
| listing_translation 有界队列 | ✅ 已完成 | finish 与 scheduled backfill 均改为 enqueue process queue 的 `listing-translation` job；worker handler 分发到 `run_listing_translation_job()`，并在完成后释放 scheduled dedupe。测试覆盖 enqueue job id、bounded scheduling 与 run 后清理。 | 后续可加队列深度/失败重试指标。 |
| LLM usage 成本预算 | ✅ 已完成 | 新增 `app.utils.ai_budget`，所有 `ModelProviderClient.generate_text()` 调用前按估算 tokens 走 SQLite `system_settings.ai_usage_budget` 持久预留；支持 `AI_DAILY_TOKEN_BUDGET` 与 `AI_MONTHLY_TOKEN_BUDGET`，超额直接跳过 LLM 调用并记录 reason。测试覆盖持久累计、日预算拒绝、月预算拒绝、禁用预算不碰 DB。 | 后续可补 API 暴露 usage 面板与真实 provider usage 回填。 |
| OpenAPI 生成 TS 类型 | ✅ 已完成 | 新增 `backend/scripts/export_openapi.py` 固化 `frontend/src/types/openapi.json`，前端用 `openapi-typescript` 生成 `src/types/api.ts`；CI 分别检查 OpenAPI JSON 与 TS 生成物 diff，防止前后端契约漂移。 | 后续可逐步把现有手写类型迁到 generated `paths/components`。 |
| BLE001 计数不增 CI | ✅ 已完成 | 新增 `backend/scripts/check_ble001_budget.py` + `ble001_budget.json`，CI 用 Ruff `--isolated --ignore-noqa` 统计生产 `app` 下真实 BLE001，当前预算 189，只允许减少不允许新增。 | 后续每清理一批 broad except 就下调预算。 |
| dead-code 检查 CI（审阅报告 §12 建议） | ✅ 已完成 | 新增 `backend/scripts/check_dead_code.py` + `dead_code_budget.json`（vulture @60% 置信，基线 415，只减不增，同 BLE001 预算模式）；CI 步骤用 `uv run --with vulture` 执行，不进 uv.lock。不变量 5（“写入点必须有读取点”）从文档约定变成机器强制；本轮实跑 `415 <= 415`。 | 每清一批死代码就下调预算；误报确认后可 `--update` 并说明原因。 |
| 每周体检邮件（新增能力） | ✅ 已完成 | 新增 `app/domains/system/weekly_report.py`：近 7 天抓取成败计数、失败 Top5 源（含失败码）、正文完整率、会话健康异常源、禁用/冷却源数，全部读 `source_fetch_log` 与 sources 结构化列；scheduler 注册周一 08:10（daily/doctor 邮件之后）；SMTP 未配置时 no-op。现已读取 `~/.pim/data/eval_history.jsonl` 并在有历史时展示 offline eval 指标趋势（precision@20、duplicate_rate、fulltext_complete_rate、source_coverage@20 及较上次变化），无历史时显示暂无；`tests/test_weekly_report.py` 覆盖聚合、空库、eval history 解析、HTML 转义、趋势渲染与 job 注册。 | T0.1 500 条人工标注集安装并跑出真实历史后，趋势会自动进入每周邮件。 |

## 4. 改进方案 WS/T 任务逐项核验

### WS0 测量与调试工具

| 任务 | 当前结论 | 证据 | 下一步 |
|---|---|---|---|
| T0.1 离线评测集 | 🟡 部分完成 | 已新增 `backend/tests/fixtures/eval_set.jsonl`、`backend/scripts/run_offline_eval.py` 与 `tests/test_offline_eval.py`，可输出 precision@20/duplicate_rate/freshness_lag/fulltext/source_diversity/source_coverage@20 等指标并写历史。`backend/scripts/export_eval_candidates.py` 与 `tests/test_export_eval_candidates.py` 可按生产内容、跨信源轮转导出待人工标注 JSONL；本轮新增自动扩窗参数 `--min-records/--expand-days-step/--max-days`，30 天不足时会继续扩大窗口直到满足目标或到达上限。本地实跑 `--limit 500 --days 30 --min-records 500 --max-days 365` 自动扩到 60 天并导出 500 条/76 源。新增 `backend/scripts/prelabel_eval_candidates.py` 与 `tests/test_prelabel_eval_candidates.py`，只写 `suggested_*` 与 `review_priority`，不写正式 `label`；本地 500 条候选预标结果为 must_see 37、ok 351、noise 112，高优先级复核 204 条。新增 `backend/scripts/review_eval_candidates.py` 与 `tests/test_review_eval_candidates.py`，可导出按 `review_priority/suggested_confidence` 排序的 TSV 审核表或单文件 HTML 审核页、将人工填好的合法 label 回填到 JSONL，并用 `status --require-complete` 检查坏标签/重复 ID/缺候选行/未标注数；本地 500 条预标候选已导出 `/tmp/pim_eval_candidates_500_review.tsv`（501 行含表头）与 `/tmp/pim_eval_candidates_500_review.html`（约 846 KB），status 显示 missing_by_priority high=204/medium=253/low=43，仍不自动接受建议。`backend/scripts/validate_eval_set.py` 与 `tests/test_validate_eval_set.py` 可在人工标注后强制检查记录数、来源覆盖、合法标签、唯一 ID，并可 `--install` 成正式 `tests/fixtures/eval_set.jsonl`；`backend/scripts/check_eval_history.py` 与 `tests/test_eval_history.py` 可强制检查 history 至少 4 个点，且最新 `precision@20` 不低于上一点；当前 500 条候选集验证失败仅因 500 条缺正式 label。 | 人工可用 HTML 页逐条审核并下载 TSV，或直接编辑 TSV；随后用 `review_eval_candidates.py status --require-complete` 验证已填完、`review_eval_candidates.py apply-sheet` 回填 JSONL，再用 `validate_eval_set.py --install` 接入 offline eval，连续跑出 ≥4 个真实历史点后用 `check_eval_history.py` 验收。 |
| T0.2 单源 dry-run API/CLI | ✅ 已完成 | 新增 `/api/sources/{source_id}/dry-run` 与 `pimctl sources dry-run`，走 CollectorStage + NormalizerStage + raw content build，返回 diagnostics/samples 并 rollback 不写库；API/CLI 测试覆盖。 | 后续可接前端按钮。 |
| T0.3 20 源抓取实测表 | ✅ 已完成 | 新增 `backend/scripts/run_fetch_field_test.py` 与 `tests/test_fetch_field_test.py`，并生成 `docs/reviews/2026-07-02-fetch-field-test.md` / `.json`。真实 dry-run：20 源，16 ok、3 warning、1 empty、0 error，would-store 130；CNN 的坏 RSS 已通过 website fallback 修复为 ok。新增 dry-run normalizer skip diagnostics 与 `docs/reviews/2026-07-04-fetch-field-followup.md` 复核 36kr=13 would-store/7 duplicate、Engadget=4 would-store/16 duplicate、Lex Fridman=3 collector/1 would-store/2 stale、CNN=30 collector/29 would-store/1 stale；YouTube collector 已优先使用 RSS feed candidate 并跳过 yt-dlp channel tab stub；website sitemap fallback 现在会尝试常见 news sitemap 并接受同注册域 sibling subdomain。 | 继续处理实测发现：Reuters 需要登录；真实 VPS/付费墙/X cookie 端到端仍需外部环境验证。 |

### WS1 抓取链路

| 任务 | 当前结论 | 证据 | 下一步 |
|---|---|---|---|
| T1.1 消灭静默失败 | ✅ 已完成 | P1-2 见上；已补 pipeline 级状态测试，覆盖 collector 全失败后 `error_count`、`last_fetch_outcome`、`fetch_failure.cooldown_until`。 | 无。 |
| T1.2 二跳正文唯一化 | ✅ 已完成 | RSS collector 不再预取 HTML；website/RSS/listing/direct hydrate 对 `source.last_content_id` 已知条目会跳过二跳；本轮新增 hydrate 前批量 same-source identity 查询，能覆盖本批所有已入库旧条目，避免稳态 feed/listing 对旧条目重复二跳。 | 后续用真实 feed 统计稳态外呼次数。 |
| T1.3 RSS 薄内容不再丢弃 | ✅ 已完成 | P1-3 见上；title-only regulator/official acceptance 放宽已完成并有单测。 | 后续真实源实测。 |
| T1.4 调度与并发一致性 | ✅ 已完成 | freshness、CollectorStage 提前 commit、finish semaphore 拆分、lifespan 按 `FETCH_CONCURRENCY` 启动 fetch workers 均已完成。 | 后续观察生产 worker backlog 与 finish 耗时指标。 |
| T1.5 重启自愈 | ✅ 已完成 | P2-11 见上；lifespan 启动会补投近 24h 未 finish 内容。 | 后续观察生产补投指标。 |
| T1.6 主链合同测试 | ✅ 已完成 | 新增 `tests/test_e2e_pipeline_contract.py`，覆盖同一 RSS 条目首次保存、第二轮 up-to-date 且不重复入库。 | 后续可扩展到 finish/score fake LLM 端到端。 |

### WS2 去重与 URL 归一化

| 任务 | 当前结论 | 证据 | 下一步 |
|---|---|---|---|
| T2.1 URL 归一化统一实现 | ✅ 已完成 | P1-4 日期段保护已完成；P1-5 覆盖 `from`、AMP 子域、tracking query、http/https、WordPress `?p=`/slug 合并。新增历史 canonical external_id 回填脚本，URL 去重单测表已覆盖 40+ 例。 | 生产执行脚本前先 dry-run 并检查冲突列表。 |
| T2.2 入库回填 canonical URL / 发布时间 | ✅ 已完成 | HTML metadata 抽取 canonical URL 与发布时间；build_content/normalizer 入库前写 metadata 与 publish_time；dedupe 同源/跨源查询加入 canonical identity。 | 历史内容迁移随 T2.1/P1-5 处理；继续做真实源抽样验证。 |
| T2.3 title simhash / duplicate_group_id | ✅ 已完成 | 新增 `title_identity` simhash helper；`build_raw_content_objects()` 生产写入 `metadata.title_fp` 与默认 `metadata.duplicate_group_id`，并保留已有上游/人工 group；score/ranking 既有 duplicate_group 消费测试通过。 | 该步骤只写入可消费信号，不按标题删除内容；后续用 T0.1 评测集调近似合并阈值。 |

### WS3 聚类与事件层

| 任务 | 当前结论 | 证据 | 下一步 |
|---|---|---|---|
| T3.1 corroboration 修正 | ✅ 已完成 | P2-17 见上；已按 registrable domain + duplicate_group_id 计独立来源，且 T2.3 已生产写入 duplicate_group。 | 后续用真实日报样本核对同源转载计数。 |
| T3.2 聚类稳定性小修 | ✅ 已完成 | `cluster_and_rank()` 先按 `article_score` 降序稳定入簇，并用 `duplicate_group_id` 强制同簇；测试覆盖高分条目优先成簇与 duplicate group 合并，且 T2.3 已生产写入 duplicate_group。 | 后续用真实日报样本核对 cluster 展示。 |
| T3.3 简报事件结构化存储 | ✅ 已完成 | `hourly_digests.items_json` 已加模型字段与 Alembic `20260702_0018`；生成任务存储结构化 event item 快照；详情 API 透出 `event_items`；前端简报详情渲染事件卡片。测试覆盖 event item 构建、API 透出与 fresh Alembic upgrade。 | 后续用真实日报样本校验卡片排序与文案质量。 |
| T3.4 embedding 决策门 | ⏸ 暂缓 | 方案本身要求评测后再决定。 | 等 T0.1 + T3.1/T3.2 后再评估。 |

### WS4 打分与反馈闭环

| 任务 | 当前结论 | 证据 | 下一步 |
|---|---|---|---|
| T4.1 用户关键词加成封顶 | ✅ 已完成 | `RuntimeScoringVocab` 不再把用户关键词并入静态 tier B，而是按匹配 term 给 salience bonus，封顶 2.0；score/explain 输出均有测试覆盖。 | 后续用真实评测集观察宽泛词 selected 占比。 |
| T4.2 词表数据化 | ✅ 已完成 | 新增 `backend/app/data/score_vocab.yaml` 与 `score_vocab_loader`；`score_vocab.py` 导入时加载 YAML 并保留 Python fallback；新增 `/api/system/score-vocab/reload` 热加载并刷新 `score_rules`/`score_explain` 绑定；测试覆盖 YAML 临时词表 reload 与 API reload。 | 后续把词表编辑入口接到管理界面前，先保持人工改 YAML + reload。 |
| T4.3 用户反馈信号落库 | ✅ 已完成 | `score_feedback` 新增 `event_type`/`event_value` 字段与 Alembic `20260702_0019`；score lab 校准反馈写 `score_calibration`；Reader/mark-read 写 `open`，favorite 写 `star`，archive 写 `hide`；列表 API 透出事件字段。测试覆盖 score lab 校准反馈、open/star/hide 行为事件与 fresh Alembic upgrade。 | 先只记录，不改排序；后续基于离线评测决定是否把反馈信号用于 rerank。 |
| T4.4 评分回归护栏 | ✅ 已完成 | 新增 `scripts/check_offline_eval_regression.py` 与 `scripts/offline_eval_thresholds.json`，CI 会跑离线 fixture 并检查 precision@20/fulltext/source_coverage 下限、duplicate/title_only 上限；测试覆盖阈值通过、min/max 违规和缺指标。 | 后续 T0.1 换成 500 条人工生产集后同步收紧阈值。 |

### WS5 精简与架构收编

| 任务 | 当前结论 | 证据 | 下一步 |
|---|---|---|---|
| T5.1 删除死代码清单 | ✅ 已完成 | orchestrator/contracts fetch 已删除；未接线的 `rss_health.dedupe_feed_entries` 已删除；当前未再发现 fetch 主链同级 DTO 孤岛。非 facade 兼容性测试已从 `app.pipeline.{collector_stage,coordinator,dedupe,normalizer_stage,storage_stage,utils}`、`app.processors.{extractor,keyword_matcher,summarizer,translator}`、`app.services.keyword_rules` shim 迁到 canonical import；`backend/app/interfaces/http/keywords.py` 也改为直连 `app.domains.ingest.keywords.rules`；`backend/tests/test_legacy_facades.py` 只验证旧路径 re-export canonical 对象。已删除 rss.py 死代码簇 `_parse_entry_with_summary` / `_fetch_page_html` / `_fetch_page_summary` / `_extract_summary_from_html` / `_entry_hydrate_sem` / `MIN_RSS_PLAIN_TEXT_CHARS`，清理 `check_before_fetch` / `permissive_session_kwargs` 无用 import，并用 `scripts/check_dead_code.py` + `dead_code_budget.json`（vulture @60%，基线 415，只减不增）进 CI，把不变量 5 变成机器强制。 | 后续清理由 dead-code 预算下调驱动，不再人工 `rg` 巡查；外部 import shim 保留。 |
| T5.2 接线激活清单 | ✅ 已完成 | session_health、persist_discovered_feed、profile fulltext/preferred_strategy 已接线；discovery default 已默认保守启用，并写可解释 diagnostics；空默认结果继续 fallback，显式关闭开关可用。 | 后续真实源覆盖率归入 T6.5/T6.6。 |
| T5.3 小 bug 顺手修 | ✅ 已完成 | `removeprefix`、freshness、提前 commit、关键词空集不过滤、listing_translation 队列化、article-hub/plain-word slug 放宽均已完成。 | 后续小 bug 另按新清单跟踪。 |
| T5.4 架构收编 | ✅ 已完成 | P2-6 已将 fetch 主链文档和代码统一到 `tasks.fetch_tasks -> domains.fetch.coordinator -> domains.fetch.collector_stage`，删除未接线 orchestrator；`RankingService` 已迁入 `domains/score/ranking.py`；`DigestService` 已迁入 `domains/enrich/digest.py`；`DoctorService` 已迁入 `domains/system/doctor.py`；`MonitorService` 已迁入 `domains/sources/monitoring.py`；`ProbeService/probe_strategies` 已迁入 `domains/sources/probe/`；`api_config_credentials` 已迁入 `platform/auth/api_config_credentials.py`；`ContentProcessor` 已迁入 `domains/ingest/content_processor.py`；`CollectorStage` 与 `Coordinator` 已迁入 `domains/fetch/`；`pipeline.utils` 与旧 pipeline stages 仅保留兼容 facade/shim；生产代码已改直连 processor/X collector/pipeline helper canonical 路径，并用 `test_architecture_boundaries.py` 防回退。 | 无。 |
| T5.5 metadata 升列/source_fetch_log | ✅ 已完成 | 新增 `SourceFetchLog` ORM 与 Alembic `20260702_0021`；`record_fetch_result()` 对 ORM source 写入 `source_fetch_log`，`summarize_profile()` 优先按表聚合 7 日 attempts/success/failure/latency/fulltext/preferred_strategy，无表数据时 fallback 到旧 metadata。本轮新增 Alembic `20260702_0022` 与 `Source.fetch_failure_*` / `fetch_cooldown_until` 列，`retry_policy`、调度冷却读取和 source API health 字段优先走列；新增 `20260702_0023` 与 `Source.rss_health_*`、`20260702_0024` 与 `Source.discovery_*`、`20260702_0025` 与 `Source.last_fetch_outcome_*`、`20260702_0026` 与 `Source.session_health_*` / `Source.session_health_alert_*`。source API metadata 投影均优先走列并保留旧 metadata fallback。测试覆盖 stale metadata 不再覆盖结构化状态。 | 无。 |

### WS6 会话可移植性与覆盖率

| 任务 | 当前结论 | 证据 | 下一步 |
|---|---|---|---|
| T6.1 会话采集 CLI | ✅ 已完成 | 新增/验收 `./pim capture-session <site_url> --out ...` 入口，作为 `./pim auth-bundle export` 的薄别名；导出仍走同一套 Auth Bundle 浏览器登录采集逻辑，可用于 X/付费站 cookie + storage_state 导出。`./pim capture-session --help` 正常转发，单测覆盖顶层分发。 | 真实 X 登录窗口需在有可视化浏览器的环境手工跑一次。 |
| T6.2 会话优先级反转 | ✅ 已完成 | `CollectorStage` 先解析 browser_session；只要 source 绑定了 browser_session，默认跳过密码 auto-login，避免会话优先源被密码登录路径误触发验证码/风控。仅当 `metadata.allow_password_login=true` 且 session 未 ready 时才允许回退密码登录；auth_ready session 始终优先。测试覆盖 ready session、未校验 session、inactive session 与显式 allow fallback。 | 无。 |
| T6.3 会话健康接线 | ✅ 已完成 | P2-7 见上；website 与 X GraphQL 认证失败路径会写结构化 session health，并由 Source API 透出；metadata 仅作为兼容投影。 | 后续真实站实测。 |
| T6.4 sitemap 发现策略 | ✅ 已完成 | Website collector 已在 RSS 后、discovery/static HTML 前尝试 sitemap；支持默认 `/sitemap.xml`、显式 `metadata.sitemap_urls`、sitemap index、同站文章 URL 过滤、上限与 diagnostics，并复用公开 listing hydrate。测试覆盖 sitemap 优先于 static fallback 与关闭开关。 | 后续用真实源跑 coverage@source。 |
| T6.5 discovery 覆盖档 | ✅ 已完成 | discovery rules 新增 bounded pagination：显式 `pagination_max_pages` 默认使用 `?page=2..N`，也支持 `pagination_param` / `pagination_url_template`；default 保守档可用 `discovery_default_listing_urls` 配多栏目、`discovery_default_pagination_max_pages` 配翻页。Website collector 现在按展开后的 listing pages 抓取，并在 `discovery_diagnostics` 写 `listing_pages_total/fetched/failed` 与分页上限。`direct_article_hydrate_limit` 已是 per-source 配置且会复用既有 session-backed paced hydration。 | 后续用真实无 sitemap 站点验证 top-30 覆盖率与 429/bot_wall 情况。 |
| T6.6 coverage@source 指标 | ✅ 已完成 | `run_offline_eval.compute_metrics()` 已输出 `source_coverage@20`、`covered_sources@20`、`total_sources`，按 `source_id` 优先、否则 source host/name 归一化统计；测试覆盖 top_k 分母。 | 后续随 T0.1 接入 500 条人工生产标注集后开始看历史趋势。 |
| T6.7 会话包导出/导入 | ✅ 已完成 | `platform/auth/bundle.py` 支持导出 host-scoped cookie/storage_state 并写 0600 bundle；`bundle_import.py` 导入后创建/更新 cookie AuthConfig、写 browser-session storage_state、同 host website 或全部 X 源自动绑定。API 测试覆盖导入创建凭据/会话/绑定源，pimctl 测试覆盖 export/import/sync payload 与远端命令编排，`./pim auth-bundle` 与 `./pim capture-session` 分发均有单测，VPS 文档给出本地导出/远端导入/一键 sync 流程。 | 后续做真实 VPS 端到端抓取实测。 |
| T6.8 刷新与告警 | ✅ 已完成 | session_health error 已进入 fetch warning channel：`expired` 映射为 `session_expired`，并新增结构化 `session_health_alert_*` 24h 去重邮件告警；coordinator 在抓取状态 commit 后异步发送 operator alert，邮件包含 source/reason/action/final_url。新增 `pimctl auth-bundle sync` / `./pim auth-bundle sync`，可在本地采集登录态、SCP 上传到 VPS、远端调用 `pimctl auth-bundle import`，并默认删除远端临时 bundle；测试覆盖 export/upload/import/cleanup 命令编排。 | 真实 VPS 上的网络连通、账号风控与抓取效果仍归入验收项 7/9/10 实测。 |
| T6.9 VPS 禁用自动登录 | ✅ 已完成 | 新增 `PIM_DISABLE_PASSWORD_AUTO_LOGIN` runtime kill switch；`maybe_refresh_auth_cookies()` 在 password auto-login 前 fail closed；VPS systemd 示例默认 `true`，`.env.example` 文档化。测试覆盖全局开关阻止 `login_and_capture_cookies`。 | 无。 |
| T6.10 X cookie-first | ✅ 已完成 | X 默认顺序固定为 `graphql -> rsshub -> nitter`；官方 API 现在需要 `metadata.strategy=api` 或 `metadata.allow_x_api_fallback=true` 才会进入 fallback。probe、信源编辑弹窗、凭据页和 README/VPS/USER_GUIDE 均标注 X API 为付费/配额 fallback。测试覆盖默认不调用 API 与显式开启后调用。 | 后续真实 X cookie 过期/恢复场景实测。 |
| T6.11 自建 RSSHub 引导 | ✅ 已完成 | `.env.example` 增加 `RSSHUB_URL` / `NITTER_INSTANCES`；README 与 VPS 文档说明 VPS 推荐自建 RSSHub、公共实例仅适合临时验证，且 RSSHub cookie 与 PIM Auth Bundle 登录态分别管理。本轮新增 `docs/rsshub-docker-compose.yml`，提供 Redis 缓存、browserless 与本机端口绑定的 RSSHub 基线部署，并在 VPS 文档接入启动/健康检查命令。 | 无。 |
| T6.12 X 失败可见 | ✅ 已完成 | X 全策略空结果已抛 failure；GraphQL cookies 缺失/过期/异常会写 `session_health`，并建议 relogin/switch_rss_only。 | 后续真实 X cookie 过期场景实测。 |
| WS6 合规边界文档 | ✅ 已完成 | `docs/VPS_DEPLOY.md` 与 `docs/USER_GUIDE.md` 明示登录态、Auth Bundle、Cookie、自动化访问、异地 IP、付费内容抓取和 API 使用的服务条款/账号风控边界，并强调仅用于有权访问的个人监控。 | 无。 |

## 5. 施工优先级建议

### 第一批：把“刚修过的核心链路”补成闭环

| 优先级 | 任务 | 原因 | 验收 |
|---|---|---|---|
| 1 | P1-2 pipeline 级失败测试 | ✅ 已完成。 | mock collector 全失败，断言 `error_count+1`、`fetch_failure.last_code`、cooldown 生效。 |
| 2 | P1-5 补 `from` 与 AMP 子域、URL 测试扩到 40 例 | ✅ 已完成。 | `tests/test_url_dedupe.py` 扩展到 53 条 URL 归一化测试。 |
| 3 | P1-1 website hydrate 已知重复跳过 | ✅ 已完成。 | 第二轮同 external_id fetch 时 hydrate mock 调用 0 次。 |
| 4 | T1.6 主链合同测试 | ✅ 已完成。 | `tests/test_e2e_pipeline_contract.py` 覆盖第二轮 saved=0 且不重复入库。 |

### 第二批：让可观测性真实

| 优先级 | 任务 | 原因 | 验收 |
|---|---|---|---|
| 5 | P2-8 feed 发现持久化 | ✅ 已完成。 | discover 成功后 `metadata_.rss_url/rss_urls` 写入。 |
| 6 | P2-9 profile fulltext/preferred_strategy | ✅ 已完成。 | Source summary 可读到 7d 正文率与策略。 |
| 7 | P2-7 session_health 接线 | ✅ 已完成。 | cookie 过期/bot wall 路径写 session_health 并给 relogin/switch_rss_only。 |
| 8 | T0.2 dry-run API | ✅ 已完成。 | dry-run 返回每阶段计数和前 5 条样例，不写库。 |

### 第三批：调度/队列/架构债

| 优先级 | 任务 | 原因 | 验收 |
|---|---|---|---|
| 9 | P2-10 finish semaphore 拆分 | ✅ 已完成。 | finish 主流程不占 LLM semaphore；LLM 调用仍受限。 |
| 10 | P2-11 启动补投 | ✅ 已完成。 | lifespan 启动后 enqueue 近 24h 未 finish 内容。 |
| 11 | P2-16 worker 并发一致 | ✅ 已完成。 | `start_workers(fetch_workers=settings.fetch_concurrency)`。 |
| 12 | P2-6/T5.4 架构收编 | 结束双主链理解税。 | 文档数据流与 grep 调用链一致，domain import 检查通过。 |

### 第四批：算法与产品能力

| 优先级 | 任务 | 原因 | 验收 |
|---|---|---|---|
| 13 | T0.1 离线评测集 | 🟡 脚手架、生产候选导出、自动扩窗、预标、人工审核 TSV/HTML 导出回填/status 门禁、标注结果校验/安装、历史趋势 gate 已完成，500 条人工标注集未完成。 | 小型 fixture + run_offline_eval 指标历史已可跑；候选导出脚本本地自动扩窗导出 500 条/76 源待标注，预标脚本生成建议，review 脚本导出 TSV 或 HTML 浏览器审核页、回填人工 label、检查审核进度/坏标签/缺行；validate 脚本会拒绝空标签/不足 500/低来源覆盖/重复 ID；check_eval_history 会拒绝历史少于 4 点或最新 `precision@20` 低于上一点。 |
| 14 | P2-17 corroboration domain 计数 | ✅ 已完成。 | 同媒体多栏目不再 strong；三独立域仍 strong。 |
| 15 | T4.1 用户关键词加成封顶 | ✅ 已完成。 | 用户关键词 salience bonus 加法封顶 2.0。 |
| 16 | YouTube transcript / event cards | 覆盖率与可解释性提升。sitemap discovery 已完成代码接线，仍需真实源覆盖率实测。 | 依真实源实测表验收。 |

## 6. 验收总表逐项结论

| 验收项 | 当前结论 | 说明 |
|---|---|---|
| 1. 已知漏抓机制清零 | 🟡 部分完成 | X 全失败、RSS 短内容、日期段、X freshness、title-only regulator/official acceptance 已修；session_expired 告警与真实源实测未完成。 |
| 2. 稳态单 feed 外呼 ≤ 1 + 新条目二跳 | 🟡 部分完成 | RSS collector 已轻量化；website/RSS/listing/direct hydrate 会跳过 `last_content_id` 已知条目，也会通过批量 same-source identity 查询跳过非 latest 旧条目；仍需真实源外呼计数实测。 |
| 3. duplicate_rate < 2% | 🔬 需实测 | URL 规则改善，但无离线评测集与历史迁移。 |
| 4. 简报事件卡片可解释 | ✅ 已完成 | hourly digest 存储 `items_json`，API 返回 `event_items`，前端详情页显示事件卡片，包含标题、摘要、来源、分数、同组标记和原文链接。 |
| 5. 无零调用 fetch 域模块，文档与真实链路一致 | ✅ 已完成 | `fetch_source_batch`/`FetchBatch` 孤岛已删除，文档与真实 fetch 主链一致；session_health 写入、warning channel、alert 去重与 source API 投影均已接线并有单测覆盖。 |
| 6. 评测历史 ≥4 个点且 precision@20 不降 | 🟡 部分完成 | T0.1 脚手架、生产候选导出、标注结果校验/安装与 `check_eval_history.py` 历史 gate 已完成，但仍缺 500 条人工生产标注集与 4 个真实历史点。 |
| 7. 付费墙会话 full 正文与过期告警 | 🟡 部分完成 | 会话 bundle、`auth-bundle sync`、session_health、过期 warning 与 operator alert 链路已有单测覆盖；仍需真实付费墙站点端到端实测。 |
| 8. sitemap/top-30 覆盖率 | 🟡 部分完成 | sitemap strategy 已接入并有单测；top-30 coverage 仍需真实源实测与离线评测记录。 |
| 9. 会话包导入 VPS 可抓付费墙正文 | 🔬 需实测 | `auth-bundle sync` 已把本地采集、SCP 上传、远端导入编排成命令；仍未在真实 VPS + 真实付费墙源上跑端到端。 |
| 10. X cookie graphql 稳定、过期可见 | 🟡 部分完成 | graphql/cookie 默认路径、X API 显式 gate、缺失/过期 session_health 与告警链路已有单测覆盖；仍缺真实 X cookie 过期/恢复实测。 |

## 7. 建议下一步拆分

1. **PR-A：回归测试与小补齐。** P1-2 pipeline 状态测试、P1-5 `from`/AMP 子域、P2-13 单测、P1-1 website 重复 hydrate skip。
2. **PR-B：可观测性接线。** feed 持久化、profile fulltext/preferred_strategy、session_health。
3. **PR-C：队列/信号量/补投。** finish semaphore、startup refinish、fetch worker concurrency。
4. **PR-D：评测基线。** eval_set、offline eval、20 源实测发现跟进。
5. **PR-E：架构收编。** orchestrator/contracts 删除或迁移，services 迁 domain，文档更新。
6. **PR-F：审查后代改项。** rss.py 死代码删除 + 测试重写、weekly_report 周报邮件 + 调度注册、check_dead_code.py 预算 CI、BLE001 预算 192→189。

## 8. 附：本次核验使用的主要命令

```bash
rg "fetch_source_batch|FetchBatch|FetchRequest|RawItem|FetchWarning" backend/app backend/tests -n
rg "session_health|classify_session|suggested_action|relogin|switch_rss_only" backend/app backend/tests frontend/src -n
rg "persist_discovered_feed|preferred_strategy|fulltext_success_rate_7d|fulltext_ok|fulltext_n" backend/app backend/tests frontend/src -n
rg "get_llm_semaphore|get_finalize_semaphore|start_workers|fetch_concurrency|use_keyword_filter|corroboration" backend/app backend/tests -n
rg "_parse_entry_with_summary|_fetch_page_html|_fetch_page_summary|_extract_summary_from_html|_entry_hydrate_sem|MIN_RSS_PLAIN_TEXT_CHARS" backend/app backend/tests -n  # zero matches expected
```

最近一次完整测试命令：

```bash
cd backend && ./.venv/bin/python -m pytest tests/test_api_sources.py tests/test_session_alerts.py tests/test_session_health.py tests/test_stage_v4_fixes.py tests/test_pipeline_stages.py::TestUpdateSourceStatus tests/test_fetch_discovery.py tests/test_fetch_retry_policy.py tests/test_alembic_fresh_upgrade.py -q  # 75 passed
cd backend && ./.venv/bin/python -m pytest tests/test_pimctl_auth_bundle.py tests/test_pim_cli.py tests/test_auth_bundle.py -q  # 21 passed
cd backend && ./.venv/bin/python -m pytest tests/test_fetch_field_test.py -q  # 3 passed
cd backend && ./.venv/bin/python -m pytest tests/test_website_collector.py::TestRssOnlyMode::test_discovered_rss_failure_falls_back_to_sitemap tests/test_fetch_field_test.py -q  # 4 passed
cd backend && ./.venv/bin/python -m pytest tests/test_fetch_field_test.py tests/test_pipeline_stages.py::TestNormalizerStageDiagnostics::test_duplicate_external_id_records_skip_diagnostic -q  # 6 passed
cd backend && ./.venv/bin/pytest tests/test_collectors_rss_youtube.py tests/test_pipeline_stages.py::TestCollectorStage::test_youtube_channel_id_marker_does_not_filter_videos tests/test_fetch_field_test.py tests/test_pipeline_stages.py::TestNormalizerStageDiagnostics::test_duplicate_external_id_records_skip_diagnostic -q  # 25 passed
cd backend && ./.venv/bin/pytest tests/test_website_collector.py::TestSameSite tests/test_website_collector.py::TestLooksLikeArticleUrl tests/test_website_collector.py::TestRssOnlyMode::test_default_sitemap_urls_include_common_news_sitemap tests/test_website_collector.py::TestRssOnlyMode::test_parse_news_sitemap_accepts_sibling_subdomain_urls tests/test_website_collector.py::TestRssOnlyMode::test_discovered_rss_failure_falls_back_to_sitemap tests/test_fetch_discovery.py -q  # 48 passed
# Direct dry-run: CNN collector=30, valid=29, would-store=29, stale=1 after sitemap/news fallback.
cd backend && ./.venv/bin/pytest tests/test_export_eval_candidates.py -q  # 4 passed
cd backend && ./.venv/bin/python scripts/export_eval_candidates.py --output /tmp/pim_eval_candidates_500_auto.jsonl --limit 500 --days 30 --min-records 500 --expand-days-step 30 --max-days 365 --max-full-content-chars 1000  # exported 500 candidates from 76 sources; expanded to 60 days
cd backend && ./.venv/bin/pytest tests/test_review_eval_candidates.py tests/test_prelabel_eval_candidates.py tests/test_validate_eval_set.py tests/test_export_eval_candidates.py -q  # 22 passed
cd backend && ./.venv/bin/python scripts/prelabel_eval_candidates.py /tmp/pim_eval_candidates_500_auto.jsonl --output /tmp/pim_eval_candidates_500_prelabeled.jsonl --json  # 500 suggestions: must_see=37, ok=351, noise=112; final label still blank
cd backend && ./.venv/bin/python scripts/review_eval_candidates.py --json export-sheet /tmp/pim_eval_candidates_500_prelabeled.jsonl --output /tmp/pim_eval_candidates_500_review.tsv  # exported 500 TSV review rows; high=204, medium=253, low=43
cd backend && ./.venv/bin/python scripts/review_eval_candidates.py --json export-html /tmp/pim_eval_candidates_500_prelabeled.jsonl --output /tmp/pim_eval_candidates_500_review.html  # exported 500-row browser review page
cd backend && ./.venv/bin/python scripts/review_eval_candidates.py --json status /tmp/pim_eval_candidates_500_prelabeled.jsonl --sheet /tmp/pim_eval_candidates_500_review.tsv  # labeled=0, remaining_unlabeled=500, no sheet errors
cd backend && ./.venv/bin/python scripts/review_eval_candidates.py --json status /tmp/pim_eval_candidates_500_prelabeled.jsonl --sheet /tmp/pim_eval_candidates_500_review.tsv --require-complete  # exits 1 until human review fills all labels
cd backend && ./.venv/bin/python scripts/review_eval_candidates.py --json apply-sheet /tmp/pim_eval_candidates_500_prelabeled.jsonl --sheet /tmp/pim_eval_candidates_500_review.tsv --output /tmp/pim_eval_candidates_500_review_applied.jsonl  # empty review sheet keeps 500 labels blank
cd backend && ./.venv/bin/pytest tests/test_validate_eval_set.py -q  # 3 passed
cd backend && ./.venv/bin/python scripts/validate_eval_set.py tests/fixtures/eval_set.jsonl --min-records 4 --min-sources 3 --json  # ok=true
cd backend && ./.venv/bin/python scripts/validate_eval_set.py /tmp/pim_eval_candidates_500_auto.jsonl --min-records 500 --min-sources 20 --max-errors 5 --json  # ok=false; 500 missing labels only
cd backend && ./.venv/bin/pytest tests/test_eval_history.py tests/test_offline_eval.py tests/test_offline_eval_regression.py -q  # 11 passed
cd backend && ./.venv/bin/python scripts/check_eval_history.py --history-path "$TMP_HISTORY" --json  # ok=true with 4 non-regressing points
cd backend && ./.venv/bin/pytest tests/test_website_collector.py::TestHydrateDirectArticlesPacing::test_known_latest_external_id_is_not_hydrated_again tests/test_website_collector.py::TestHydrateDirectArticlesPacing::test_existing_same_source_items_are_not_hydrated_again -q  # 2 passed
cd backend && ./.venv/bin/pytest tests/test_pipeline_stages.py::TestNormalizerStageDiagnostics -q  # 2 passed
cd backend && ./.venv/bin/pytest tests/test_content_quality_filters.py tests/test_q1_narrow_excepts.py tests/test_pipeline_stages.py::TestPipelineUtils tests/test_architecture_boundaries.py -q  # 37 passed
cd backend && ./.venv/bin/pytest tests/test_legacy_facades.py tests/test_pipeline_stages.py tests/test_keyword_filter.py tests/test_content_quality_filters.py tests/test_e2e_pipeline_contract.py tests/test_architecture_boundaries.py -q  # 85 passed
cd backend && ./.venv/bin/pytest tests/test_legacy_facades.py tests/test_processors.py tests/test_keyword_matcher_safety.py tests/test_keyword_matcher_coverage.py tests/test_stage_b_fixes.py tests/test_architecture_boundaries.py -q  # 122 passed
cd backend && ./.venv/bin/pytest tests/test_keyword_rules.py tests/test_legacy_facades.py tests/test_architecture_boundaries.py tests/test_api_keywords.py -q  # 23 passed
cd backend && ./.venv/bin/pytest tests/test_weekly_report.py tests/test_collectors_rss_youtube.py tests/test_scheduler_jobs.py -q  # 25 passed
cd backend && ./.venv/bin/python - <<'PY'
import yaml
from pathlib import Path
data = yaml.safe_load(Path("../docs/rsshub-docker-compose.yml").read_text())
assert {"rsshub", "browserless", "redis"} <= set(data["services"])
assert data["services"]["rsshub"]["ports"] == ["127.0.0.1:1200:1200"]
PY
cd backend && ./.venv/bin/ruff check .
cd backend && ./.venv/bin/python scripts/check_ble001_budget.py
cd backend && uv run --with 'vulture>=2.11' python scripts/check_dead_code.py  # 415 <= 415
cd backend && ./.venv/bin/python scripts/check_domain_imports.py --phase=7
git diff --check

# Earlier full-suite baseline:
cd backend && ./.venv/bin/python -m pytest -q  # 1498 passed
cd backend && ./.venv/bin/python -m ruff check .
cd backend && ./.venv/bin/python scripts/check_domain_imports.py --phase=7
cd backend && ./.venv/bin/python scripts/check_ble001_budget.py  # 189 <= 189
cd backend && uv run --with 'vulture>=2.11' python scripts/check_dead_code.py  # 415 <= 415
git diff --check
cd frontend && npm test
cd frontend && npm run lint
cd frontend && npm run build
```
