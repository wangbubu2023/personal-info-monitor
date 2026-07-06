# PIM 改进施工方案

**日期：** 2026-07-02
**依据：** `2026-07-02-pim-expert-review-report.md`（下称"审阅报告"，引用其问题编号如 P1-1）
**基线：** commit `1c2fce6`，v1.3.1

---

## 0. 第一性原理：从需求倒推系统该长什么样

PIM 的唯一产品目标：**以最低成本、最短延迟、最少噪声，把用户关心的"新信息"排到最前面。**

把这句话拆开，得到四个可度量的系统目标，全部施工项都必须挂到其中至少一个：

| 目标 | 指标 | 当前状态（静态推断） | 施工后目标 |
|---|---|---|---|
| **不漏**（覆盖率） | 漏抓率 = 未入库的应抓条目占比 | X 静默失败、数字段误判重、X 60min 窗口、RSS<100字丢弃 → 存在系统性漏抓 | 已知漏抓机制 = 0 |
| **快**（时延） | freshness lag P90（发布→入库） | 受调度 5min tick + interval 支配，可接受 | P90 ≤ interval + 10min |
| **净**（噪声率） | duplicate_rate + 低质入库率 | utm/scheme 不归一 → 单篇列表有重复 | duplicate_rate < 2% |
| **准**（排序质量） | precision@20（简报/首页前 20 的人工满意度） | 无测量手段 | 建立基线后 +20% |

由此推出五条**系统不变量**，是所有改动的判断标准：

1. **每条新信息的全文只被抓取一次。** 二跳正文必须发生在去重之后、且全系统只有一个实现。（现状违反：RSS 去重前逐条二跳、二跳四处实现）
2. **失败必须可见，且必须影响下一次调度。** collector 不允许把失败吞成空列表。（现状违反：P1-2）
3. **同一篇文章在库中只有一行。** URL 归一化是去重的唯一入口，规则集中一处。（现状违反：P1-4/5）
4. **排序必须可校准。** 没有离线评测集之前，不改任何权重/阈值/词表结构。（现状违反：无评测手段）
5. **不为没人消费的数据付出代码与运行成本。** 写入点必须有读取点，否则删除。（现状违反：session_health、feed 缓存、profile 字段等）

**施工总原则：先建测量（WS0），再修主链（WS1-2），然后调算法（WS3-4），最后做减法（WS5）。** 算法改动一律先过离线评测，主链改动一律带回归测试与 feature flag。

---

## 1. 工作流总览与排期

```
Sprint 1 (第1周)     WS0 评测基线 ┐
                     WS1 抓取修复 ┘ 并行，互不依赖
Sprint 2 (第2-3周)   WS2 去重归一（依赖 WS0 的重复率测量）
                     WS1 收尾（二跳唯一化）
Sprint 2 (第2-3周)   WS6-A 会话可移植性（付费墙/X/VPS 共用底座）
Sprint 3 (第4-5周)   WS3 聚类事件层  WS5 精简  WS6-B sitemap 覆盖（并行）
Sprint 4 (第6-8周)   WS4 打分与反馈闭环  WS5 架构收编  WS6-C 会话刷新与告警
持续                 每 Sprint 末跑一次评测集，指标回归即回滚
```

| 工作流 | 内容 | 对应审阅报告 / 用户诉求 |
|---|---|---|
| WS0 | 评测基线与调试工具 | §6.3、§8、§12 |
| WS1 | 抓取链路：修 bug + 二跳唯一化 + 调度一致性 | P1-1/2/3、P2-10/11/13/14/16、§3 |
| WS2 | 去重与 URL 归一化 | P1-4/5、§6.1 |
| WS3 | 聚类与事件层 | P2-17、§6.2 |
| WS4 | 打分、个性化与反馈闭环 | §6.3、需求问题 9 |
| WS5 | 精简无效模块与架构收编 | P2-6/7/8/9、§2、§3.4 |
| **WS6** | **会话可移植性 + 覆盖率：付费墙聚合、网页全集抓取、VPS 登录态、免费 X** | **用户长期未解问题 1-4** |

---

## 2. WS0 — 先立测量：评测基线与调试工具（Sprint 1，~3 人日）

> 原理：不变量 4。没有测量就没有"优化"，只有"改动"。这是全方案里投入产出比最高的一步，且不碰生产逻辑，零风险。

### T0.1 离线评测集

- 从现库导出近 30 天内容，人工标注 500 条：`must_see / ok / noise` 三档 + `is_duplicate_of` 标记。存 `backend/tests/fixtures/eval_set.jsonl`（title/summary/url/publish_time/人工标签）。
- 新脚本 `backend/scripts/run_offline_eval.py`：复用 `rescore_contents.py --dry-run` 的回放骨架，输出六个指标：`precision@20`、`duplicate_rate`、`freshness_lag_p50/p90`、`fulltext_complete_rate`、`title_only_rate`、`source_diversity@20`。
- 结果落 `~/.pim/data/eval_history.jsonl`，每次跑追加一行——趋势即回归警报。

### T0.2 单源 dry-run API（审阅报告 §8 建议）

- `POST /api/sources/{id}/dry-run`：执行 CollectorStage + NormalizerStage 但不写库，返回 `{raw_count, 每阶段丢弃原因计数, discovery_diagnostics, 样例条目前5}`。积木（各阶段诊断计数）已存在，主要是编排与序列化。
- `pimctl sources dry-run <id> --json` 同步提供。
- **验收：** 对一个 RSS 源与一个网站源，dry-run 输出能解释"为什么这轮只入库 N 条"。

### T0.3 抓取实测表（补审阅报告 §5.4 未完成项）

- 按报告样本集跑 20 源实测，填评估表，作为 WS1/WS2 的 before 基线。1 人日。

---

## 3. WS1 — 抓取链路：修复静默失败 + 二跳唯一化（Sprint 1-2，~8 人日）

> 原理：不变量 1、2。抓取域的问题不是"策略不够聪明"，而是"失败不可见 + 重复劳动"。先把链路做诚实、做省，再谈策略优化。

### T1.1 消灭静默失败（P1-2，最高优先级）

**改动：**
- `x_twitter.py::fetch`：全策略耗尽时 `raise FetchFailureError(make_failure(UNKNOWN, message="all X strategies exhausted", ...))`；各策略失败时用 `classify_exception` 记录最后一个失败，耗尽时抛"最具体"的那个（如最后见到 http_429 就抛 429）。
- `youtube.py:80-82`、`website.py::_fetch_static:1105-1107`、`rss.py:92-97`：catch-all 分支改 `raise FetchFailureError(classify_exception(exc))`。
- `pipeline/coordinator.py`：行为不变——它已经能正确处理异常路径；删除的只是"空列表=成功"的歧义。
- 兼容点：`_fetch_with_playwright(raise_on_error=False)` 的静默返回保留（它是显式的降级分支）。

**验收测试（防回归）：**
- `test_x_collector_all_strategies_fail_marks_source_error`：mock 四策略全 raise → 断言 source.error_count 递增、`metadata_.fetch_failure.last_code` 写入、下一轮 `is_due` 受 backoff 影响。
- 同型测试各写一个给 youtube / website static / rss。

### T1.2 二跳正文唯一化（P1-1 + §3.3 重复实现收敛）

**目标形态：collector 只产出"清单"（标题/链接/时间/摘要 teaser），全文二跳只发生在 finish 阶段的 `article_body.py`，且只对"确认是新行"的内容执行。**

分两步降风险：

**Step A（Sprint 1，止血）：** RSS hydrate 前置去重检查。
- `rss.py::fetch`：解析完 20 条 entry 后、hydrate 前，批量查询 `Content.external_id IN (...)`（需要把 db session 传入或回调；最小侵入做法是在 `CollectorStage.execute` 里把"已存在 external_id 集合"注入 `source._known_external_ids`，RSS collector 据此跳过 hydrate）。
- 效果：稳态下每轮二跳请求从 ~20 次降到"仅新条目数"（通常 0-3）。
- **验收：** 测试断言同一 feed 第二次 fetch 时 `_fetch_page_html` 的 mock 调用次数为 0。

**Step B（Sprint 2，收敛）：** 移除 RSS/website collector 内的正文 hydrate，统一走 finish。
- `rss.py`：删 `_parse_entry_with_summary` 的页面抓取，仅保留 feed 自带 content/summary；`validate_content` 阈值问题随 T1.3 一并解决。
- `website.py::_maybe_hydrate_public_listing_contents` / `_hydrate_direct_articles`：保留（listing 条目必须有正文才可评分，且它有 Playwright/paywall 能力，article_body 没有）——**但**给它加与 Step A 相同的"已知 external_id 跳过"逻辑。
- `article_body.website_body_needs_public_fetch` 已有"缺正文才抓"判断，天然幂等，不动。
- reader 的独立拉取（第 4 处实现）：改为先调 `fetch_public_article_body`，仅当需要 cookie/Playwright 时走自有路径（P3 级，可延后）。
- **验收：** 全链 E2E（见 T1.6）中，一条新 RSS 文章从 fetch 到 score 全程只发生一次文章页 HTTP 请求。

### T1.3 RSS 薄内容不再丢弃（P1-3）

- `rss.py::validate_content` 退化为 `super().validate_content`（title+url），删除 100 字门槛（`MIN_RSS_PLAIN_TEXT_CHARS` 保留用于"是否值得二跳"的提示，不用于丢弃）。
- 薄内容的取舍统一交给 `acceptance.py`（现有 summary≥50 字门）。公告类源放宽：`authority_type in {official, regulator}` 时 title-only 允许进入 `candidate`（改 `assess_fetch_acceptance` 增加白名单分支 + `stamp` 时标记 `acceptance_relaxed=regulator`）。
- **验收：** title-only 的监管公告在 Dashboard 可见、状态可解释、不进 selected。

### T1.4 调度与并发一致性（P2-13/16 + §3.5）

- `normalizer.py:150-158`：非 feed 类默认窗口 `max(fetch_interval*2, 60)` 分钟，消除 X 源 interval>60min 的结构性漏抓。
- `main.py` 启动：fetch worker 数 = `settings.fetch_concurrency`（或明确改文档说明并发由 worker 数决定，二选一，推荐前者）。
- `finish.py:22-24`：信号量拆分——finalize 的网络部分用新的 `get_finalize_semaphore()`（默认 8），仅 `apply_pipeline_summary` 内部持 LLM semaphore。
- `collector_stage.py:74`：去掉自动绑定 auth 的 `db.commit()`，改为仅 set 属性由 coordinator 统一提交。

### T1.5 重启自愈（P2-11）

- `main.py` lifespan 启动时：`SELECT id FROM contents WHERE json_extract(metadata_,'$.fetch_acceptance') IS NULL AND fetched_at > now-24h` → 逐条 `enqueue_ingest_finish`（限速 1/s，避免启动风暴）。
- **验收：** 集成测试——入库后不跑 finish 直接"重启"（重建队列），断言补投后行获得 acceptance/score 字段。

### T1.6 主链合同测试（审阅报告 §10-Q10 ⑤）

- `tests/test_e2e_pipeline_contract.py`：本地 fixture HTTP server（feed + 两篇文章页）+ fake LLM → 跑 `fetch_source → finish_content` 全链，断言：入库数、`fulltext_status=full`、`fetch_acceptance=accepted`、`article_score` 存在、重复第二轮 saved=0 且无二跳请求。这个测试是后续所有重构的安全网，**必须先于 Step B 合入**。

---

## 4. WS2 — 去重与 URL 归一化（Sprint 2，~4 人日）

> 原理：不变量 3。去重的正确层次是：①URL 归一（确定性，覆盖 90%）→ ②内容指纹（simhash，覆盖跨协议/转载）→ ③语义（可选，延后）。现状①有错、②缺失。

### T2.1 URL 归一化统一实现（P1-4/5）

新建 `app/utils/url_canonical.py`（或在 `url.py` 内重写），单函数 `canonicalize(url) -> str`，规则按序：

1. scheme 统一 `https`；host 小写、剥 `www.`、剥端口默认值；
2. 剥 tracking 参数：`utm_*`、`fbclid`、`gclid`、`ref`、`source`、`spm`、`from`（白名单制保留其余 query，如 `?p=`、`?id=`）；剥 fragment；
3. 剥 AMP 形态：路径尾 `/amp`、`amp/`，`amp.` 子域还原主域（保守：只处理尾缀，子域还原放 P3）；
4. WordPress `?p=ID` 规则保留；
5. **数字段规则收紧**：仅当数字段前一段 ∈ `ARTICLE_HUB_SEGMENTS`（articles/story/news/post…）且数字段**不是 8 位日期形态**（`19|20\d{6}`）时才作为文章 ID；
6. 尾斜杠/重复斜杠归一（现有逻辑保留）。

- `canonical_article_external_id` / `normalize_source_url_for_dedupe` 改为薄包装调用它；`dedupe.py`、`pipeline/utils.py`、`dedupe_raw_contents` 全部经此单点。
- **验收：** 表驱动测试 ≥40 例（含审阅报告列的全部反例：utm、http↔https、`/news/20260630/a` vs `/b`、`?p=123`、/amp、尾斜杠、中文 URL 编码）。跑 T0.1 评测集，`duplicate_rate` 下降且**漏抓类误合并归零**（用日期段站点样本专项验证）。

### T2.2 入库时回填 canonical URL 字段

- 二跳拿到 HTML 后读 `<link rel=canonical>` / `og:url`（`structured_article.py` 顺手提取，加一个返回字段），写 `metadata_.canonical_url`，dedupe 的 identity_filters 增加 `Content.original_url == canonical_url` 一项。
- 同时补 `article:published_time` / JSON-LD `datePublished` 提取回填 `publish_time`——一并解决"网站源发布时间最弱"问题（§5.3），并砍掉 `resolve_website_publish_time` 的逐篇兜底请求（不变量 1）。

### T2.3 跨协议/转载指纹去重（Step 2）

- 新增 `title_simhash`（host 无关、标题归一后 64-bit simhash）存 `metadata_.title_fp`。
- 同源不同 URL：simhash 距离 ≤3 且 publish_time 差 <48h → 判重（替换现有"标题+时间精确相等"的弱语义去重）。
- 跨源：**不删行**（保留 corroboration 信息），只写 `metadata_.duplicate_group_id`（simhash 桶 id），供 WS3 聚类与前端折叠使用。
- **验收：** 评测集 `is_duplicate_of` 标注的召回 ≥80%，误杀 = 0（人工抽查 50 例）。

---

## 5. WS3 — 聚类与事件层（Sprint 3，~4 人日）

> 原理：事件层的目的只有一个——"多源佐证的重要事件排上去"。它的两个输入（簇成员、独立源数）都被上游重复问题污染；**先修输入，再谈算法升级**。embedding 属于"输入干净之后仍不够"才考虑的手段。

### T3.1 corroboration 修正（P2-17，~20 行改动）

- `score_event.py::compute_corroboration`：计数键从 `source_id` 改为 **registrable domain**（用 `tldextract` 或简化的二级域规则）；同 domain 的多栏目/RSS+website 双配置自动合一。
- 通稿抑制：簇内 `duplicate_group_id` 相同的条目按一源计。
- `_is_official_source` 保持；`single_high` 判定不变。
- **验收：** 单测——同一媒体两个源报同一事 → tier=single_*；三个不同 domain → strong。评测集上人工核对 20 个簇的 tier 正确率。

### T3.2 聚类稳定性小修

- `ranking_service.py::cluster_and_rank`：入簇前按 `article_score` 降序排序（分数高者先建簇，簇心更代表事件核心，降低顺序敏感性）；`duplicate_group_id` 相同者强制同簇。
- momentum 的"近 6h"对只有日期粒度的条目（YouTube）改用 `fetched_at`——已是 fallback，但当前条件是 `publish_time or fetched_at` 取前者，改为取两者较新者。
- **验收：** 评测集聚类人工核对：错聚/漏聚各 ≤10%。

### T3.3 简报按事件结构化存储（审阅报告 §7）

- `store_digest` 增存 `items_json`：`[{event_key, topic, content_ids, event_score, corroboration_tier}]`（LLM 主路径也先选簇再综述，材料按簇组织）；前端 DigestPage 渲染事件卡片，点开见成员与"为什么排这"（event_score 三分量）。
- synthesis 材料带 `fulltext_status`，prompt 加约束："仅摘要来源不得引申未见细节"。
- **验收：** 简报每条可回链到成员文章；抽查无"摘要来源被演绎出细节"案例。

### T3.4 embedding 决策门（不排期，立规则）

仅当 T3.1-3.2 落地后评测仍显示"漏聚 >15% 或 duplicate_rate >3%"，才启动 sqlite-vec + bge-small 实验：范围限简报窗口 ≤80 条、离线评测先行、规则路径保底。否则不做。

---

## 6. WS4 — 打分与反馈闭环（Sprint 4，~6 人日）

> 原理：规则评分的天花板不在规则本身，而在"没有校准回路"。方向不是推翻 v2 换模型，而是：词表数据化（降维护成本）→ 用户信号回流（获得标注）→ 有数据之后再谈学习排序。

### T4.1 用户关键词加成封顶（需求问题 9 的直接修复）

- `score_vocab_runtime.py`：用户词命中从"并入 entity tier B、显著性不低于 A 档"改为**加法封顶**：`salience += min(2.0, 每词1.0)`，不改档位；`score_vocab_matched_user_terms` 照旧记录。
- explain（`score_explain.py`）增加"用户关键词加成 +x"条目，UI 可见。
- **验收：** 含宽泛关键词（"AI"）的评测子集上，selected 占比回落至与无关键词基线相差 <10%。

### T4.2 词表数据化

- `score_vocab.py` 的 LANE/ENTITY/EVENT/COMMERCE 等词表导出为 `backend/app/data/score_vocab.yaml`，模块启动加载 + `POST /api/system/reload-vocab` 热更新；代码里只留结构与合并逻辑。
- 保留旧版快照对比（文档 §7 checklist 已要求）。
- **验收：** 改 yaml 不重启生效；`test_score_v2_rules.py` 全绿（锚点不动）。

### T4.3 用户反馈信号落库（先记录，不改排序）

- `contents` 增列 `user_signal`（open/star/hide + 时间），前端 ContentCard 三个动作接线（read_status 已有，补 star/hide）。
- 30 天后回看数据量，决定是否做轻量 rerank（如 hide 的 lane/domain 降权）——**本 Sprint 不做任何排序改动**，只埋数据。

### T4.4 评分回归护栏

- 任何 T4.x 合入前后各跑一次 T0.1 评测，`precision@20` 不得下降；CI 中锚点测试（地缘 vs 科技平衡）保持。

---

## 7. WS5 — 精简无效模块与架构收编（Sprint 3-4 穿插，~6 人日）

> 原理：不变量 5。做减法的优先级高于任何新功能——每个死模块都在持续收"理解税"。分"直接删"与"接线激活"两类处理，判据：**该数据/能力是否服务四个产品指标之一**。

### T5.1 直接删除清单（零生产调用，验证于审阅报告附录）

| 对象 | 处置 |
|---|---|
| `domains/fetch/orchestrator.py` + `domains/contracts` 中仅被其引用的 `FetchBatch/FetchRequest/RawItem/FetchWarning` | **删除**（决策见 T5.4：选择"承认 pipeline 为正史"路线）；`test_fetch_orchestrator.py` 同删 |
| `rss_health.dedupe_feed_entries` | 删除（功能已由 `dedupe_raw_contents` 覆盖） |
| `podcast.audio_duration` 恒 None 字段 | 补齐 itunes:duration 解析（3 行）或删字段，推荐补齐 |
| `compute_domain_match`（scoring.py 自注 legacy） | 删除 + 清理引用 |
| services 层纯 re-export facade（`scoring_service.py`、`content_quality_service.py`） | 迁移调用点后删除 |

### T5.2 接线激活清单（有产品价值、只差最后一公里）

| 对象 | 接线方式 | 服务指标 |
|---|---|---|
| `session_health.py` | X/website 认证路径失败时调用分类，结果写 `metadata_.session_health`，serialize_source 透出 `suggested_action`（relogin/switch_rss_only）| 不漏（登录态失效可见） |
| `rss_health.persist_discovered_feed` | `website.py:899` discover 成功后调用 | 快+省（每轮省 1 次首页抓取 + ≤9 次 HEAD） |
| `profile.fulltext_ok/n`、`preferred_strategy` | coordinator 从批内 `fulltext_status` 聚合传入；X collector 把成功策略名传入 | 可观测（前端正文完整率不再空转） |
| `discovery` 保守档默认启用 | 无 RSS 的网站源自动 `{mode:listing, listing_urls:[source.url], freshness_days:7}`，diagnostics 常开进 Source 页 | 不漏+可解释 |

### T5.3 小 bug 顺手修（与上述文件重叠，随包合入）

- `discovery/listing.py:34` `lstrip("www.")` → `removeprefix("www.")`（P2-12）。
- `website_helpers.py` `_looks_like_slug_segment` 放宽：article-hub 后一段无条件接受（P3 误拒 `blog/hello` 型）。
- `coordinator.py:140-143` 关键词过滤空集：降级为不过滤 + `keyword_filter_misconfigured` 状态码（P2-15）。
- `finish.py:186` listing_translation 改走 process 队列而非裸 `create_task`（P3 背压）。

### T5.4 架构收编决策：承认 pipeline 为正史（推荐）

两条路线中选**B**：

- ~~A. 完成 Phase 2 反转：把 coordinator/CollectorStage 迁入 domains/fetch~~ —— 收益纯属命名美学，风险与工作量大。
- **B. 承认现状：** `app/pipeline/` 重命名整理为 `domains/fetch/pipeline/`（一次 git mv + import 修正，行为零变化），删 orchestrator/contracts 死代码，改 ARCHITECTURE.md/MODULE_BOUNDARIES.md 与真实链路一致。`check_domain_imports.py` 相应更新边界。
- 同包处理：`ranking_service.py` → `domains/score/ranking.py`；`digest_service.py` → `domains/enrich/digest_service.py`；`article_body.py:167` 的 `app.collectors.x_twitter` importlib 改 canonical 路径；`finish.py` 改直接 import canonical。
- **验收：** `check_domain_imports.py --phase=8`（新增规则：domains 不得 import app.services）全绿；全测试套通过；文档数据流图与 grep 到的真实调用链一致。

### T5.5 metadata 升列（Sprint 4，配 Alembic 迁移）

- `contents` 增列：`article_score REAL`、`selection_status TEXT`（迁移脚本从 JSON 回填，双写过渡一个版本，读侧 coalesce）。hourly 候选查询、Dashboard 排序改走列 + 索引。
- `source_fetch_log` 表（append-only：source_id/ts/outcome/failure_code/saved/latency_ms）替代 `fetch_profile` 日桶 JSON；`summarize_profile` 改查表聚合。fetch_profile JSON 保留只读一个版本后删除。
- **验收：** 迁移可回滚（`./pim rollback`）；hourly 候选查询 EXPLAIN 走索引；Source 页 7d 指标数值与迁移前一致（抽 5 源核对）。

---

## 7bis. WS6 — 会话可移植性与覆盖率（用户长期未解问题 1-4，Sprint 2-4，~10 人日）

> 第一性原理：问题 1（付费墙）、3（VPS 登录态）、4（X 收费）**是同一件事**——"我有合法凭据，如何在自动化/远程环境里可靠地用它"。答案不是"更聪明地自动登录"（自动填表单本身就是最强 bot 信号），而是**搬运一个真人已经登录好的浏览器会话**（cookies + storage_state），并解决它的过期刷新。问题 2（网页全集）是独立的覆盖率问题，核心不是"全站爬虫"而是"用站点主动提供的 sitemap/多栏目拿到近期重要文章全集"。
>
> 关键判断：这些能力**代码里大多已存在但半接线**（`browser_session`、`storage_state_path`、`data_dir/cookies|storage-state/`、`auth/bundle_import.py`、discovery 的 `max_links`/多 listing_urls），WS6 主要是**接线 + 补采集/刷新工作流 + 放开覆盖档**，而非从零造轮子。

### WS6-A 会话采集与注入底座（Sprint 2，解决问题 1+3+4 的公共底座，~4 人日）

**目标：把"密码自动登录"从默认路径降级为兜底；"导入已登录会话"成为一等公民。**

- **T6.1 会话采集 CLI/流程。** 新增 `./pim capture-session --site wsj.com`：在**本机**用带头模式的 bundled Chromium 打开站点，人工完成登录（含验证码/2FA），关闭时自动导出 `storage_state.json` 到 `data_dir/storage-state/<host>.json` 并登记到 source 的 `auth_config`。X 账号同理导出 `auth_token`+`ct0`。
  - 复用点：`get_browser_context` 已支持 `storage_state`/`user_data_dir`；`bundle_import.py` 已有 bundle 导入骨架，扩成"导出"对称能力。
- **T6.2 会话优先级反转。** `CollectorStage.execute`：当存在有效 `storage_state`/`browser_session` 时**跳过**密码自动登录（现有 `session_auth_ready` 短路逻辑已是雏形，扩为默认策略）；密码登录仅在无会话且 source 显式 `allow_password_login=true` 时触发。消除审阅报告提到的"WSJ 自动登录招验证码→假阳性 auth_captcha"。
- **T6.3 会话健康接线（复用 WS5-T5.2）。** `session_health.py` 接入 X/website 认证失败路径：cookie 过期/bot wall → 分类为 `session_expired`/`bot_wall`，写 `metadata_.session_health.suggested_action`（`relogin`/`switch_rss_only`），Source 页明确提示"请重新导入 xx 会话"，而非静默失败。
- **验收：** 对一个付费墙站点，导入本机会话后手动抓取拿到 full 正文；会话删除/过期后，Source 页出现明确的"需重新登录"提示而非绿色假成功。

### WS6-B 网页覆盖率：sitemap 优先 + discovery 覆盖档（Sprint 3，解决问题 2，~3 人日）

> 纠正方向：信息监控要的是"近期重要文章全集"，不是"全站所有页面"。遍历式爬虫会陷入翻页/封禁/陈旧内容。正确的高覆盖手段按性价比排序：sitemap > 多栏目 listing+翻页 > 提高 hydrate 上限。**遍历式全站抓取不做**（违反不变量 1，且信噪比极低）。

- **T6.4 sitemap 发现策略（最高杠杆，当前完全缺失）。** 新增 `sitemap` collector 分支，发现顺序插在 RSS 之后、HTML 抓取之前：探测 `/sitemap-news.xml`、`/news-sitemap.xml`、`robots.txt` 里声明的 sitemap；解析 `<url><lastmod>`/news 扩展的 `<news:publication_date>` + `<news:title>`。产出即"近期文章列表 + 精确发布时间 + 标题"——正是 top-N 最新重要文章，且比解析首页 HTML 可靠一个数量级，顺带解决审阅报告 §5.3 的"网站发布时间最弱"。
  - 命中 sitemap 的源，发布时间准确率应接近 RSS。
- **T6.5 discovery 覆盖档放开。** `max_links` 默认 20→可配到 50（`_MAX_LINKS_CEILING` 已是 50）；支持多 `listing_urls`（你填 3-5 个栏目页）；新增**同 listing 翻页**（`?page=2..N`，`max_depth` 仍锁 1、不递归）。`direct_article_hydrate_limit` 提为 per-source（默认对重点源开到 30），复用已有的 paced hydration（会话场景串行 + 随机间隔）压封禁风险。
- **T6.6 覆盖率指标进评测。** T0.1 评测集加 `coverage@source`（实抓条目 / sitemap 或人工清点的应抓条目），作为 WS6-B 的 before/after 度量。
- **验收：** 对一个有 news-sitemap 的新闻站，一轮抓取覆盖近 24h 内 ≥90% 的文章（对 sitemap 清单）；无 sitemap 的站点经多栏目+翻页覆盖 top-30；全程无 429/bot_wall（pacing 生效）。

### WS6-C VPS 会话搬运与刷新（Sprint 4，解决问题 3 的远程闭环，~3 人日）

> VPS 无头，无法交互登录 → 会话在**本机采集**，**搬运**到 VPS，并解决**过期刷新**。

- **T6.7 会话包导出/导入对称。** `./pim export-session-bundle` 在本机打包 `storage-state/` + `cookies/`（加密，复用 `ENCRYPTION_KEY`）；VPS 侧 `./pim import-session-bundle <file>` 解包落位。`VPS_DEPLOY.md` 补该工作流。
- **T6.8 刷新与告警。**
  - 半自动：本机 companion 脚本（cron）定期 `export → scp → import`，一条命令；
  - 抗衰减：VPS 默认 `PIM_BROWSER_BACKEND=patchright`（stealth）+ 首页 warm-up（代码已有），延长会话寿命、降低刷新频率；
  - 告警：T6.3 的 `session_expired` 触发时，经已有通知渠道（daily digest / doctor digest）提醒"VPS 上 xx 会话已过期，请重新上传"。
- **T6.9 VPS 上禁用自动登录。** VPS 环境（无 DISPLAY / 无人值守）强制 `allow_password_login=false`——那里没有人工过验证码的可能，自动登录必然卡死。
- **验收：** 本机导出会话包→VPS 导入→付费墙源在 VPS 上抓到 full 正文；会话过期时收到通知，重新上传后恢复。

### WS6-D 免费 X 策略固化（并入 Sprint 2，随 WS6-A，~1 人日）

> 你**不需要付费 API**——代码里 API 本就是最后兜底，第一顺位 `graphql` 走的是你自己账号的免费登录 cookie。

- **T6.10 默认策略改为 cookie-first。** 默认 `strategy=graphql`（用 T6.1 导入的 `auth_token`+`ct0`）；`api` 仅在显式配置 bearer token 时启用，UI 明确标注"付费"。**强烈建议用小号/备用号**（文档提示），低速率（长 interval）压封号风险。
- **T6.11 自建 RSSHub 引导。** 文档补"自建 RSSHub + 你的 cookie"作为 graphql 的稳定替代；`RSSHUB_URL` 指向自建实例（已支持）。公共 Nitter/rsshub.app 降为最末兜底（其 2026 年可用性需实测，不作主力）。
- **T6.12 X 失败可见（依赖 WS1-T1.1）。** 修掉 X 全策略失败伪装成功的静默 bug 后，cookie 过期会经 T6.3 变成 `session_expired` 告警——你终于能知道"是 cookie 过期了"而不是"今天没推文"。
- **验收：** 用小号 cookie 走 graphql 稳定抓取；cookie 过期时有明确告警而非静默零结果；全程不触发付费 API。

### WS6 合规边界（写入文档，不写入代码）

付费墙聚合是你对**自己已付费订阅**的个人阅读用途，技术可行；但多数站点 ToS 禁止自动化访问，X 亦然。降低风险的工程手段：单会话、低频率、小号、stealth。账号风险由使用者承担——`USER_GUIDE.md` 应明确提示，让用户知情决策，系统不做任何"破解"（我们只是搬运用户自己的合法会话）。

---

## 8. Bug 修复对照表（审阅报告 → 施工任务）

| 报告编号 | 摘要 | 施工任务 | Sprint |
|---|---|---|---|
| P1-1 | RSS 去重前二跳 | T1.2 | 1-2 |
| P1-2 | 静默失败+清零 | T1.1 | 1 |
| P1-3 | RSS<100字丢弃 | T1.3 | 1 |
| P1-4 | 数字段误合并 | T2.1 | 2 |
| P1-5 | utm/scheme 不归一 | T2.1 | 2 |
| P2-6 | orchestrator 死代码 | T5.1/T5.4 | 3-4 |
| P2-7 | session_health 未接线 | T5.2 | 3 |
| P2-8 | feed 发现不持久化 | T5.2 | 3 |
| P2-9 | profile 字段恒空 | T5.2 | 3 |
| P2-10 | LLM 信号量误用 | T1.4 | 1 |
| P2-11 | 重启丢任务 | T1.5 | 1 |
| P2-12 | lstrip 误用 | T5.3 | 3 |
| P2-13 | X 60min 窗口 | T1.4 | 1 |
| P2-14 | 提前 commit | T1.4 | 1 |
| P2-15 | 关键词空集全拒 | T5.3 | 3 |
| P2-16 | 并发配置不生效 | T1.4 | 1 |
| P2-17 | corroboration 虚增 | T3.1 | 3 |

---

## 9. 风险控制与回滚

- **评测先行：** WS2/3/4 每个合入以 T0.1 指标为门禁；`precision@20` 或 `duplicate_rate` 劣化即回滚。
- **Feature flag：** 行为型改动挂 `PIM_FEATURE_*`（已有机制）：`CANONICAL_URL_V2`、`DISCOVERY_DEFAULT_ON`、`ACCEPTANCE_REGULATOR_RELAX`；WS6 增 `SESSION_IMPORT_FIRST`（会话优先于密码登录）、`SITEMAP_DISCOVERY`、`X_COOKIE_FIRST`。默认开，出问题一键回退。VPS 环境额外强制 `allow_password_login=false`（T6.9）。
- **金丝雀源：** 选 5 个代表性源打 `metadata_.canary=true`，新行为先只对金丝雀生效 48h（判定在 collector/ingest 入口，一个 if）。
- **数据迁移：** T2.1 归一化规则变更会让部分历史 external_id 与新 key 不一致 → 迁移脚本对近 30 天行重算 `external_id`（hash 类不动），避免升级后首轮大面积"新内容"假象。T5.5 双写过渡。
- **顺序纪律：** T1.6 合同测试必须先于 T1.2 Step B 与 T5.4 合入；T0.1 必须先于一切算法改动。

## 10. 验收总表（施工完成的定义）

1. 已知漏抓机制清零：X 全失败必转 error；日期段站点同日多篇全入库；X 长间隔无 stale 误杀；title-only 公告可见。
2. 稳态下单 feed 单轮外呼 ≤ 1（feed 本体）+ 新条目数（二跳），实测表对照验证。
3. `duplicate_rate < 2%`（评测集），Dashboard 无 utm/scheme 型重复。
4. 简报事件卡片可解释（三分量+成员），同媒体多栏目不再虚增 corroboration。
5. `grep` 全库无零调用的 fetch 域模块；文档数据流图与真实链路一致；`check_domain_imports --phase=8` 通过。
6. 评测历史 ≥4 个数据点且 precision@20 较基线不降。
7. **（WS6）付费墙源导入本机会话后拿到 full 正文；会话过期有明确告警而非假成功。**
8. **（WS6）有 news-sitemap 的站点覆盖近 24h ≥90%；无 sitemap 站经多栏目+翻页覆盖 top-30，全程无 bot_wall。**
9. **（WS6）本机会话包可导入 VPS 并抓到付费墙正文；过期触发通知。**
10. **（WS6）X 用小号 cookie 走 graphql 稳定抓取，零付费 API，过期可见。**
