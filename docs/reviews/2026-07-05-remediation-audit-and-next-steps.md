# PIM 整改落实全量审查 + 第一性系统性再反思

**日期：** 2026-07-05（v2，替代同日早前的抽查版）
**输入：** 审阅报告（07-02）、施工方案（07-02）、核验跟踪表（文档 3）
**审查方式：** 文档 1/2 的**每一个编号项**（P1×5、P2×12、§3 改进×17、WS0–WS6 任务×33）逐项在当前工作区代码做独立静态核验。未执行动态运行验证（venv 为 macOS 二进制，审查环境为 Linux 沙箱）。

---

## 1. 逐项审查总表

### 1.1 审阅报告 P1（5/5 全部核实为已完成）

| 编号 | 问题 | 文档3声明 | 我的独立核验 | 结论 |
|---|---|---|---|---|
| P1-1 | RSS 去重前逐条二跳 | ✅ | `rss.py::fetch` 只走 `_parse_entry`，注释明确 hydration 移至 finish；website 侧 `_known_duplicate_external_id`(L171) + `_known_existing_content_indexes`(L211) 在 hydrate 前跳过已知条目 | ✅ 核实。但见 §2-③（死代码残留） |
| P1-2 | collector 吞异常假成功 | ✅ | rss.py:97、youtube.py:59/104、x_twitter.py:133、website.py:1484 均 `raise FetchFailureError(classify_exception(...))`；X 全策略耗尽抛最后一个失败 | ✅ 核实 |
| P1-3 | RSS <100 字被丢弃 | ✅ | `validate_content` 只校验 title/url + 二进制体（rss.py:109-122），docstring 明确 acceptance 拥有质量决策 | ✅ 核实 |
| P1-4 | 8 位日期段误判文章 ID | ✅ | url.py:8 `_DATE_YYYYMMDD_RE`，L86 数字段规则排除日期形态 | ✅ 核实 |
| P1-5 | utm/scheme 不归一 | ✅ | url.py:68 剥 `utm_*` + `_TRACKING_QUERY_KEYS`（含 fbclid）；`test_url_dedupe.py` 存在 | ✅ 核实 |

### 1.2 审阅报告 P2（12/12 全部核实为已完成）

| 编号 | 问题 | 我的独立核验 | 结论 |
|---|---|---|---|
| P2-6 | orchestrator 死代码 | git status 显示 `contracts/fetch.py` 等已删除；fetch 域现存 coordinator.py/collector_stage.py（收编入 domains） | ✅ 核实 |
| P2-7 | session_health 未接线 | coordinator/collector_stage/x_twitter/website/session_alerts 6 处消费；`session_alerts.py::stamp_session_health_alert` 存在 | ✅ 核实 |
| P2-8 | feed 发现不持久化 | website.py:1071-1073 discover 成功后调 `persist_discovered_feed` | ✅ 核实 |
| P2-9 | profile fulltext 恒空 | coordinator.py:36-63 `record_fetch_result` 传入 `fulltext_ok/preferred_strategy` | ✅ 核实 |
| P2-10 | LLM 信号量误用 | finish.py:22 使用 `get_finalize_semaphore()` | ✅ 核实 |
| P2-11 | 重启丢任务 | lifespan.py:48 `enqueue_unfinished_content_on_startup`，L139 启动调用 | ✅ 核实 |
| P2-12 | `lstrip("www.")` | listing.py:54 已改 `removeprefix("www.")` | ✅ 核实 |
| P2-13 | X 60min 窗口 | normalizer.py:219 `max(interval_minutes * 2, 60)` | ✅ 核实 |
| P2-14 | 提前 commit | collector_stage.py 全文件无 `.commit()` | ✅ 核实 |
| P2-15 | 关键词空集全拒 | coordinator.py 存在 `keyword_filter_misconfigured` | ✅ 核实 |
| P2-16 | 并发配置不生效 | lifespan.py:134 `start_workers(fetch_workers=settings.fetch_concurrency)` | ✅ 核实 |
| P2-17 | corroboration 虚增 | score_event.py:51 `_registrable_domain` 计数 | ✅ 核实 |

### 1.3 审阅报告 §3 其他改进项（17 项）

| 项 | 我的独立核验 | 结论 |
|---|---|---|
| services 迁 domains | `domains/score/ranking.py`、`enrich/digest.py`、`system/doctor.py`、`sources/monitoring.py`、`sources/probe/`、`platform/auth/api_config_credentials.py`、`ingest/content_processor.py` 全部存在 | ✅ 核实（文档3自评🟡是因残余债，方向正确） |
| 生产代码消费 shim | finish.py 无任何 `app.processors/collectors/pipeline` import；`test_architecture_boundaries.py`、`test_legacy_facades.py` 存在 | ✅ 核实 |
| 质量过滤四处重复 | `get_website_content_reject_reason` 只剩 pipeline/utils（facade）与 ingest 域内引用，parser/normalizer/build_content 已不做业务拦截 | ✅ 核实 |
| Source.metadata_ 混写升列 | source.py:49-60+ `fetch_failure_*`/`fetch_cooldown_until`/`rss_health_*`/`discovery_*`/`last_fetch_outcome_*`/`session_health_*` 列齐全；`source_fetch_log.py` ORM 存在；Alembic 0021–0026 六个迁移在 | ✅ 核实 |
| score 升列 | content.py:66-68 `article_score/final_score/selection_status` + 三个索引；Alembic 0020 | ✅ 核实 |
| canonical/og:url 回填 | `structured_article.py:540 extract_article_page_metadata` | ✅ 核实 |
| 发布时间从 HTML 回填 | build_content.py:150、normalizer.py:48 `publish_time_source="html_metadata"` | ✅ 核实 |
| discovery 保守档默认 | rules.py:247 `resolve_discovery_rules`，模块 docstring 明确保守默认+fall through | ✅ 核实 |
| trafilatura 兜底 | `domains/ingest/extractor.py` 引用 trafilatura | ✅ 核实 |
| YouTube transcript | youtube.py:29 `_CAPTION_BUCKETS`（requested/subtitles/automatic），transcript status 标记 | ✅ 核实 |
| Podcast duration | podcast.py:71-87 解析 `itunes_duration` | ✅ 核实 |
| X 外链主体化 | x_twitter.py:621-706 `_extract_external_article_url` + `x_external_article_fetch_limit` | ✅ 核实 |
| listing_translation 队列化 | finish.py:174-176 `enqueue_listing_translation_job` | ✅ 核实 |
| LLM 成本预算 | `app/utils/ai_budget.py` 存在 | ✅ 核实 |
| OpenAPI→TS | `scripts/export_openapi.py` + `frontend/src/types/{openapi.json,api.ts}` | ✅ 核实 |
| BLE001 预算 CI | `scripts/check_ble001_budget.py` + `ble001_budget.json` | ✅ 核实 |
| 死代码清理（T5.1 自评🟡） | contracts 已删，但 rss.py:124-212 `_parse_entry_with_summary`/`_fetch_page_html` 成为新死代码（全库零调用方） | 🟡 与自评一致，新增反例见 §2-③ |

### 1.4 施工方案 WS/T 任务（33 项）

| 任务 | 我的独立核验 | 结论 |
|---|---|---|
| T0.1 离线评测集 | `eval_set.jsonl` 仅 4 条 fixture；export/validate/check_eval_history/check_offline_eval_regression 四脚本 + 对应测试均存在 | 🟡 与自评一致：**脚手架全、数据空**。这是全局关键路径 |
| T0.2 dry-run API/CLI | `interfaces/http/sources/dry_run.py` + pimctl `sources dry-run`（app.py:154） | ✅ 核实 |
| T0.3 20 源实测表 | `docs/reviews/2026-07-02-fetch-field-test.{md,json}` + `2026-07-04-fetch-field-followup.md` 存在 | ✅ 核实（Reuters 登录墙等遗留与自评一致） |
| T1.1–T1.5 | 同 P1-2/P1-1/P1-3/P2-13·14·10·16/P2-11 | ✅ 全核实 |
| T1.6 主链合同测试 | `tests/test_e2e_pipeline_contract.py` 存在 | ✅ 核实 |
| T2.1/T2.2 | 同 P1-4/5 + canonical/发布时间回填；`backfill_canonical_external_ids.py` 存在但**未执行** | ✅ 代码核实 / ⚠️ 迁移未跑 |
| T2.3 title simhash | `domains/ingest/title_identity.py` + build_content 写入 | ✅ 核实 |
| T3.1 corroboration | 同 P2-17 | ✅ 核实 |
| T3.2 聚类稳定性 | ranking.py:57-87 按 article_score 排序入簇 + `_duplicate_group_id` 强制同簇 | ✅ 核实 |
| T3.3 简报事件结构化 | hourly_digest.py:28 `items_json`；`event_items` 贯穿 hourly/tasks→repository→schemas→interfaces/http/digest；前端 `DigestView.tsx` 消费 | ✅ 核实（前后端全链） |
| T3.4 embedding 决策门 | 无 embedding 代码 | ⏸ 按计划暂缓，正确 |
| T4.1 关键词封顶 | score_vocab_runtime.py:62 `user_keyword_salience_bonus`（capped additive） | ✅ 核实 |
| T4.2 词表数据化 | `app/data/score_vocab.yaml` + system.py:93 `POST /score-vocab/reload` | ✅ 核实 |
| T4.3 反馈信号落库 | score_feedback.py:25 `event_type/event_value`；open（contents_crud:246、contents_reader:137）、star（:269）、hide（:183）全接线 | ✅ 核实 |
| T4.4 评分回归护栏 | `check_offline_eval_regression.py` + `offline_eval_thresholds.json` | ✅ 核实（但守的是 4 条玩具数据） |
| T5.2–T5.5 | 接线/小修/收编/升列，证据同上各行 | ✅ 全核实 |
| T6.1 capture-session | `./pim` L36/L1623 分发存在 | ✅ 核实 |
| T6.2 会话优先级反转 | collector_stage.py:33 `_allow_password_login` 默认 False、L150 先解析 browser_session | ✅ 核实 |
| T6.3 会话健康接线 | 同 P2-7 | ✅ 核实 |
| T6.4 sitemap 策略 | website.py 41 处 sitemap 逻辑（含 news sitemap、sibling subdomain） | ✅ 核实 |
| T6.5 discovery 覆盖档 | rules.py:104-107 `pagination_max_pages/param/url_template` | ✅ 核实 |
| T6.6 coverage@source | run_offline_eval.py:168/198 `source_coverage@20` | ✅ 核实 |
| T6.7 会话包导出/导入 | `platform/auth/bundle.py` + `domains/fetch/auth/bundle_import.py` | ✅ 核实 |
| T6.8 sync + 告警 | cli/pimctl/app.py:474 `handle_auth_bundle_sync` + L596 远端编排；session_alerts 24h 去重 | ✅ 核实 |
| T6.9 VPS 禁自动登录 | settings.py:129 `pim_disable_password_auto_login` + refresh.py:45 fail-closed | ✅ 核实 |
| T6.10 X cookie-first | x_twitter.py:107 `["graphql","rsshub","nitter"]`，api 需显式 gate（L150） | ✅ 核实 |
| T6.11 自建 RSSHub | `docs/rsshub-docker-compose.yml` 存在 | ✅ 核实 |
| T6.12 X 失败可见 | 同 P1-2 + session_health | ✅ 核实 |

**总评：67 个编号项中，代码侧声明 100% 与实现一致，无一虚报；未完成项（T0.1 标注、各真实实测）的自评也诚实。** 这份跟踪表可以作为可信基线。

---

## 2. 审查发现的偏差（文档 3 未记录）

① **【最高风险】全部整改未提交。** HEAD 仍是 `1c2fce6`（v1.3.1 审阅基线），258 个文件的改动以未提交工作区形态存在，包含 9 个 Alembic 迁移和多处删除。一次误操作即全损。

② **施工方案 §9 的风险纪律被跳过。** 计划中的行为型 feature flag（`CANONICAL_URL_V2`、`DISCOVERY_DEFAULT_ON`、`ACCEPTANCE_REGULATOR_RELAX`、`SESSION_IMPORT_FIRST`、`SITEMAP_DISCOVERY`、`X_COOKIE_FIRST`）**均未实现**，金丝雀源机制（`metadata_.canary`）全库零命中。新行为全部默认硬开启，只有零散的 per-source 开关（discovery.mode=off、sitemap 开关、X api gate）。即：**改动的回滚手段与计划不符**。考虑到改动已做完且测试全绿，务实做法不是补 flag，而是把"回滚单位"改为 git：分批提交 + tag，出问题按 commit revert。

③ **rss.py 留下新死代码。** `_parse_entry_with_summary`/`_fetch_page_html`（L124-212）零调用方——恰好违反不变量 5。审阅报告 §12 提议的 dead-code CI（vulture）仍未建立，这是"session_health 式完工未接线"的镜像问题（"下线未删除"）。

④ **历史迁移未执行。** `backfill_canonical_external_ids.py` 未跑，历史 external_id 与新归一化规则不一致，升级后首轮会出现"假新内容"波峰，且新旧 URL 形态并存期间去重不完整。

⑤ **周报未调度。** `analyze_weekly_crawls.py` 只是脚本，scheduler 中无 weekly 报告任务——可观测性建好了管道，但没人定期看。

---

## 3. 第一性系统性再反思

回到唯一目标：**每天打开一个页面，用最少时间读完我关心的所有新信息（含付费墙/X/YouTube），AI 帮我预消化。**

完整的系统闭环应是：

```
信源 → 抓取 → 精炼(去重/评分/聚类) → 简报 → 【阅读】 → 【反馈】 → 回到精炼
                     ↑____________________________________________|
```

对照这个闭环，逐段反思：

**反思一：管道前半段已经超建，边际收益趋零。** 三份文档、258 个文件、67 个整改项，全部落在"信源→简报"。这一段现在的工程质量（失败分类闭环、会话搬运、sitemap、事件卡片）超过了大多数商业 RSS 阅读器。继续在此投入的每一小时，收益都低于花在闭环缺口上的一小时。**结论：宣布前半段功能冻结，直到后述缺口补齐。**

**反思二：系统没有一个真实的质量数字。** "准"（precision@20）和"净"（duplicate_rate）至今为零测量——评测门禁守着 4 条玩具数据。所有算法验收、阈值收紧、embedding 决策全部被 T0.1 卡死，而 T0.1 是整个计划里唯一纯人肉的任务，也因此最容易永远躺在"部分完成"。**解法是改造任务而非等待执行力：** 用 LLM 对 500 条候选预标三档（系统本身就有 LLM 通道），你只仲裁分歧样本（经验上 20–30%，约 100–150 条，2 小时内）；或先用 200 条冷启动——precision@20 只关心头部，样本量要求本就不高。

**反思三：凭据生命周期决定系统寿命。** 你最高价值的信源（付费墙、X）全部依赖搬运的会话，而会话过期是**常态而非异常**。系统能否长期活着，取决于一个此前没人定义的指标：**会话失效到恢复的平均时长（MTTR）**。告警链路已建好但从未在真实过期场景验证过；`capture-session → auth-bundle sync` 的实操摩擦决定你会不会在告警后拖延三天。建议把"从收到 session_expired 邮件到恢复抓取 ≤10 分钟"作为明确验收，并演练一次。

**反思四：阅读端是无人区，而它才是初衷。** "方便、高效地读"发生在前端和消费动线上，三份文档合计给了它不到 5% 的篇幅。具体缺口：简报生成了但没有送达渠道（你得主动去开网页）；没有阅读流（键盘导航、读完即下一篇、按事件折叠已读）；没有"稍后读"；付费墙正文抓到了，但 Reader 排版是否好到让你不跳回原站，从未被当作验收项。**这些不是锦上添花——聚合阅读器的全部价值在阅读侧兑现。**

**反思五：反馈闭环有数据无日程。** open/star/hide 已落库（核实），但"30 天后回看"没有写进任何日历或调度。无决策日期的延后等于放弃。定死：8 月 5 日，看三个数：事件总量、star/hide 的 lane 分布、以及 star 内容的 final_score 分布（若 star 集中在低分内容，说明排序与你的真实偏好背离——这一个数字就能校准整个评分体系的方向）。

**反思六：单人系统必须自证健康。** 没有 SRE，可观测性做得再全，没人每周看等于没做。把 doctor + weekly crawl 分析 + eval history 合成一封每周一早上的"体检邮件"（邮件通道已存在），内容三段：本周抓取失败 Top5 源、duplicate/title-only 率、会话健康状态。**规则：任何不进推送渠道的指标视为不存在。**

**反思七：复杂度是持续税，需要预算约束。** 1400 个后端测试、9 个新迁移、fetch 域 30+ 文件，由一个人维护。本轮整改已经历"审阅→施工→核验"三轮文档，说明系统复杂度已到需要专门流程管理的程度。建议给自己立规矩：**每新增一个模块，删除等量旧代码**（本次 rss.py 死代码就是没执行这条的结果）；dead-code CI（vulture 白名单制）落地，把"不变量 5"从文档约定变成机器强制。

---

## 4. 可落实建议清单（带排期与验收）

### 第 0 步：锁住成果（本周内，半天）

| # | 动作 | 验收 |
|---|---|---|
| 1 | 分批提交 258 文件：建议按 PR-A 修复+测试 / PR-B 可观测性 / PR-C 队列架构 / PR-D 评测 / PR-E WS6 五批，或最少一次性 commit + tag `v1.4.0-rc1` | `git status` 干净；tag 可 checkout |
| 2 | 提交前删 rss.py:124-212 死代码 | 全库 `_parse_entry_with_summary` 零命中 |
| 3 | 跑 `backfill_canonical_external_ids.py --dry-run` 审冲突 → commit 执行 | 冲突清单人工确认；升级首轮无"假新内容"波峰 |

### 第 1–2 周：真实世界验证（每项半天）

| # | 动作 | 验收 |
|---|---|---|
| 4 | 付费墙端到端：`./pim capture-session` 采集一个你已订阅的站 → 手动抓取 | Content 的 `fulltext_status=full`；Reader 可读全文 |
| 5 | X 过期演练：小号 cookie 走 graphql 稳定抓取后，人为删 cookie | 24h 内收到 session_expired 邮件（而非绿色假成功）；重新导入 ≤10 分钟恢复 |
| 6 | VPS 闭环：`pimctl auth-bundle sync` 本地→VPS，付费墙源在 VPS 抓到 full 正文 | 验收项 9 关闭 |
| 7 | T0.1 破局：LLM 预标 500 条三档 → 人工只仲裁分歧（预计 ≤150 条）→ `validate_eval_set.py --install` | 评测集就位；`run_offline_eval` 出第一个真实 precision@20 |
| 8 | 把 `analyze_weekly_crawls` + doctor + eval 摘要接入每周一体检邮件（复用 operator alert 通道） | 收到第一封周报 |

### 第 3–6 周：运营期 + 阅读端（前半段功能冻结）

| # | 动作 | 验收 |
|---|---|---|
| 9 | 连续 4 周每周跑 offline eval → 攒 ≥4 个真实历史点，`check_eval_history` 转真门禁；同步收紧 `offline_eval_thresholds.json` | 验收项 6 关闭 |
| 10 | 简报送达：每日简报邮件/推送，附事件卡片回链 | 你连续一周不主动开网页也能读到简报 |
| 11 | 阅读动线：j/k 键盘流、read-later、按事件簇折叠已读；以"读完 20 条的按键/点击数"为度量做一轮优化 | 前后对比数据 |
| 12 | 挑 2–3 个最常读的付费源专项调优 Reader 排版（图片/代码块/脚注） | 你主观愿意在 PIM 内读完而不跳原站 |
| 13 | dead-code CI：vulture 白名单制进 CI | 新死代码无法合入 |

### 决策点日历（写进日程，到期必须给结论）

| 日期 | 决策 | 判据 |
|---|---|---|
| 8月5日 | 反馈信号是否进 rerank | star/hide 事件量 ≥200 且 star 的 final_score 分布显示排序偏差 |
| 8月中 | embedding 决策门（T3.4） | 真实评测显示漏聚 >15% 或 duplicate_rate >3% 才启动，否则永久搁置 |
| 8月中 | 词表/权重调优解冻 | eval history ≥4 点后才允许 |

### 明确不做（维持纪律）

atoms 维持冻结；全站遍历爬虫不做；评测集就位前不动任何权重/阈值/词表结构；不新增信源类型（先把四类跑到真实验证全绿）。

---

## 4bis. 2026-07-05 审查后已代改项（待本地全套测试确认后随本轮 commit）

| 改动 | 内容 | 沙箱验证 |
|---|---|---|
| rss.py 死代码删除 | 删 `_parse_entry_with_summary`/`_fetch_page_html`/`_fetch_page_summary`/`_extract_summary_from_html`/`_entry_hydrate_sem`/`MIN_RSS_PLAIN_TEXT_CHARS`（427→285 行）；清理 `check_before_fetch`/`permissive_session_kwargs` import | AST/ruff 通过；全库无残余引用 |
| 测试同步 | 删 2 个专测死代码的用例；`test_rss_fetch_does_not_hydrate_entries_before_dedupe` 重写为 `test_rss_fetch_issues_no_page_requests_before_dedupe`——改在网络边界（`fetch_public_http_text`）锁不变量，比 patch 私有方法更强 | AST/ruff 通过 |
| 周报体检邮件 | 新增 `app/domains/system/weekly_report.py`（近 7 天抓取成败/失败 Top5 源/正文完整率/会话健康/禁用与冷却数，全部读结构化列）；scheduler 注册周一 08:10；新增 `tests/test_weekly_report.py`（4 用例） | 聚合+渲染逻辑在沙箱真实 SQLite 全断言通过 |
| dead-code 预算 CI | 新增 `scripts/check_dead_code.py` + `dead_code_budget.json`（vulture@60% 置信，基线 415，只减不增，同 BLE001 模式）；CI 步骤用 `uv run --with vulture` 免改 uv.lock | 脚本实跑通过 |
| BLE001 预算下调 | rss.py 清理顺带减 3 个 broad except，预算 192→189（按"清理即下调"策略） | `check_ble001_budget.py` 通过 |

沙箱已验证：`ruff check app` 全绿、BLE001/domain-imports/dead-code 三个门禁全绿。**未验证：** pytest 全套（沙箱无 macOS venv），commit 前需本地跑 `pytest -q` 与前端三件套。

## 5. 结论

67 个整改项逐项核验，代码与声明 100% 一致，工程质量与文档诚实度都过硬。真正的问题在代码之外：成果未提交（含计划内的回滚机制未建）、质量度量仍是零、真实世界验证全空、以及"高效阅读"这个初衷在三轮文档中始终无人认领。下一阶段的第一性答案：**冻结管道前半段，锁成果、测真实、建周报，然后把工程力气花到阅读与反馈闭环——那里才是这个系统存在的理由。**
