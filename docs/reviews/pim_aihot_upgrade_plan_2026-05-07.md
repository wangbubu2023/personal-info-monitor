# PIM 借鉴 AIHOT 的升级改造计划

日期：2026-05-07

## 0. 执行摘要（便于立项评审）

本次升级聚焦三件事：一是让“抓取质量与信源质量”可见并可控；二是让“模型打维度分 + 脚本决策”成为稳定主链路；三是把简报从“文章堆叠”升级为“事件优先”。

建议按 6 个阶段推进，优先落地 metadata 方案与 3 小时报，避免一开始做重迁移或引入复杂 embedding。整体策略是“先可用、再可测、后增强”。

执行上建议拆成两条并行但有依赖的主线：

- 基础设施主线：信源星级、全文状态、评分 schema、3 小时窗口。这条可以较快落地。
- 智能精选主线：维度评分、脚本总分、事件聚类、日报重构。这条必须经过回测和 Gate 审查。

上线成功以量化指标判断，而不是主观感受。建议以最近 14 天滚动窗口评估：

- 3 小时报空报告率：较当前下降 30% 以上。
- 简报重复事件率：较当前下降 40% 以上。
- `selected` 内容人工认可率：达到 70% 以上。
- `blocked` 内容误判为高置信推荐的比例：低于 2%。
- 评分失败导致流程阻塞的比例：0（必须降级而非中断）。

## 1. 背景与目标

本计划基于两类输入：

- 用户提供的 AIHOT 经验文章：信源筛选、分维度打分、脚本计算、事件聚类、日报生成。
- PIM 当前代码结构：已有 `contents.full_content`、`contents.metadata`、`sources.metadata`、日报 API、`hourly_digest` 服务包、`RankingService` 轻量事件聚类。

改造目标不是把 PIM 做成另一个热点站，而是把 PIM 从“抓取后摘要”升级为“抓取质量可见、信源有星级、内容可评分、事件可聚类、推荐理由可解释”的个人信息决策系统。

目标形态：

- 抓取层：优先获取全文，但不因全文不可用而阻塞整个系统。
- 评分层：模型输出结构化维度分，脚本计算最终分。
- 聚类层：从文章列表升级为事件列表，降低重复信息噪声。
- 简报层：从小时报调整为 3 小时报和日报。
- 展示层：给出清晰的推荐理由、置信度、信源星级和全文状态。

非目标（本期明确不做）：

- 不做“全网热点榜单”产品化运营能力。
- 不做跨平台社交传播指标体系（点赞/转发全量建模）。
- 不在第一阶段引入大规模 embedding 全量重算。
- 不为了“看起来聪明”而把所有决策都交给模型。

## 2. 当前 PIM 可复用基础

### 2.1 数据模型

当前 `Content` 已有：

- `title`
- `summary`
- `translated_summary`
- `full_content`
- `keyword_matches`
- `metadata`

当前 `Source` 已有：

- `name`
- `type`
- `url`
- `fetch_interval`
- `auth_required`
- `auth_config_id`
- `metadata`

这意味着第一阶段可以优先把新字段放入 JSON metadata，减少数据库迁移和 UI 联动成本。等验证稳定后，再把高频查询字段迁移成正式列或独立表。

### 2.2 简报与聚类

当前已有：

- `backend/app/services/hourly_digest/`：小时简报的窗口、候选、生成、fallback。
- `backend/app/tasks/hourly_digest_tasks.py`：小时简报编排入口。
- `backend/app/services/ranking_service.py`：基于 token/Jaccard 的轻量事件聚类和排序。
- `backend/app/api/digest.py`：日报和小时报 API。

这些模块可以继续沿用，不需要另起一套平行系统。

## 3. 核心原则

### 3.1 全文优先，但不把全文作为硬阻塞

高质量评分最好依赖全文，这一点成立。但 PIM 的信源类型复杂，包括 RSS、网页、X、YouTube、付费墙网站和需要登录态的网站。如果把“抓到全文”作为评分硬前提，会导致大量内容无法进入后续流程。

建议引入两个概念：

- `fulltext_status`：本条内容抓取质量。
- `score_confidence`：本次评分的置信度。

推荐状态：

- `full`：完整正文。
- `partial`：正文不完整，但有较多段落或摘要。
- `summary_only`：只有摘要、description 或 RSS 内容。
- `title_only`：只有标题。
- `blocked`：疑似 paywall、登录态失效、403、反爬或内容不可见。

评分时：

- `full` 可用于完整维度评分。
- `partial` 可评分，但降低置信度。
- `summary_only` 只适合判断相关性、信源权威性、初步重要性。
- `title_only` 只进入低成本预筛，不应进入高分精选。
- `blocked` 不应强行让模型猜测，可进入重试队列或登录态检查。

### 3.2 模型负责判断维度，脚本负责最终决策

不要让模型直接输出“是否推荐”或“最终重要性分”。模型适合读文本、抽取理由、给多个维度打分；最终选择、阈值、权重、降权和版本管理应该由代码完成。

这样做的好处：

- 评分逻辑可回测。
- prompt 不会不断膨胀。
- 分数变化可解释。
- 不同频道可以有不同阈值。
- 可以稳定做 A/B 或版本回滚。

### 3.3 先事件，后文章

PIM 现在更像“内容流”。升级后应逐步改成“事件流”：

- 多篇文章可能属于同一事件。
- 事件有主文章、相关报道、来源列表、时间线和热度。
- 简报优先推荐事件，而不是重复推荐文章。

### 3.4 简报要减少打扰

小时报对 PIM 这类个人信息系统偏频繁，容易造成“为了生成而生成”。建议调整为：

- 3 小时报：监控最近 3 小时的重要变化。
- 日报：复盘全天重要事件，适合作为主要阅读入口。

## 4. 新增数据设计

### 4.1 Source metadata 扩展

第一阶段放在 `sources.metadata`：

```json
{
  "source_stars": 3,
  "authority_type": "official_blog",
  "domain_focus": ["ai", "model", "policy"],
  "source_weight": 1.25,
  "noise_level": "low",
  "preferred_for_canonical": true
}
```

字段说明：

- `source_stars`：信源星级，取值为 `1` / `2` / `3`。
- `authority_type`：官方博客、官方 X、公司公告、论文、媒体、KOL、聚合源等。
- `domain_focus`：该信源主要覆盖的领域。
- `source_weight`：最终分数加权因子。
- `noise_level`：噪声水平，用于精选阈值调整。
- `preferred_for_canonical`：事件主文章选择时是否优先。

建议星级：

| 星级 | 类型 | 例子 | 策略 |
| --- | --- | --- | --- |
| 三星 | 官方、一手、论文、监管、项目发布 | 公司博客、论文页、官方 changelog、监管公告 | 高权重、优先作为事件主来源 |
| 二星 | 官方社媒、专业媒体、可信 KOL、newsletter | 官方 X、创始人账号、专业媒体、行业作者 | 中高权重，重视时效，但需要噪声控制 |
| 一星 | 聚合、泛资讯、低稳定或待验证源 | 泛 RSS、转摘站、综合聚合页 | 低权重、严格阈值，主要作为补充信号 |

星级只表示“信源可信度和一手程度”，不表示“内容一定重要”。例如三星官方公告如果与用户关注主题无关，仍应被 `topic_relevance` 拉低；一星聚合源如果只是转载三星源，也不应因为多次出现而被误判为高价值原创事件。

建议增加两个防混淆约束：

- `source_stars` 不直接决定是否入选，只参与权威性加权和主文章选择。
- `domain_focus` 与内容主题匹配后，才允许使用完整的星级 bonus；主题不匹配时只保留较小权威加成。

### 4.2 Content metadata 扩展

第一阶段放在 `contents.metadata`：

```json
{
  "fulltext_status": "full",
  "content_quality": 0.86,
  "extraction_method": "playwright",
  "score_version": "pim-score-v1",
  "score_basis": "full_content",
  "score_confidence": 0.88,
  "dimension_scores": {
    "topic_relevance": 8,
    "novelty": 7,
    "impact": 8,
    "authority": 9,
    "actionability": 6,
    "risk": 3
  },
  "final_score": 84.5,
  "selection_status": "selected",
  "recommendation_reason": {
    "why_now": "今天首次由官方发布。",
    "why_matters": "可能影响模型选择、成本结构或产品路线。",
    "source_context": "来自三星官方源，并被多个二星信源跟进。",
    "evidence": "公告中明确给出发布时间、版本号和适用范围。",
    "caveat": "目前缺少第三方实测。",
    "suggested_action": "进入日报重点观察。",
    "confidence": 0.84
  }
}
```

字段说明：

- `fulltext_status`：正文可用程度。
- `content_quality`：抽取文本的质量分。
- `score_version`：评分公式版本。
- `score_basis`：评分依据。
- `dimension_scores`：模型输出的维度分。
- `final_score`：脚本计算后的最终分。
- `selection_status`：`selected` / `candidate` / `rejected` / `deferred`。
- `recommendation_reason`：结构化推荐理由。
- `recommendation_reason.confidence`：推荐理由层面的整体可信度（0 到 1）。它与 `score_confidence` 不同，前者表达推荐理由是否站得住，后者表达评分输入证据是否充分。

### 4.3 后续事件表设计

验证通过后建议新增事件表，而不是长期只塞 metadata。

`event_clusters`：

```text
id
event_key
title
summary
category
canonical_content_id
cluster_score
source_count
item_count
first_seen_at
last_seen_at
status
metadata
created_at
updated_at
```

`event_cluster_items`：

```text
event_cluster_id
content_id
role
similarity
created_at
```

`role` 可取：

- `canonical`
- `supporting`
- `duplicate`
- `followup`
- `contradiction`

### 4.4 metadata 到正式表的迁移条件

第一阶段使用 metadata 是为了降低改造风险，但不能长期把所有高频能力都堆在 JSON 里。建议设置明确迁移条件：

| 数据 | 第一阶段位置 | 迁移触发条件 | 长期位置 |
| --- | --- | --- | --- |
| 信源星级 | `sources.metadata.source_stars` | 需要按星级高频筛选、排序、统计 | `sources.source_stars` 正式列 |
| 正文状态 | `contents.metadata.fulltext_status` | 需要列表筛选和质量报表 | `contents.fulltext_status` 正式列 |
| 最终分 | `contents.metadata.final_score` | 需要高频排序、分页、索引 | `contents.final_score` 正式列 |
| 事件关系 | `contents.metadata.event_key` | 事件页、日报、跨窗口追踪稳定使用 | `event_clusters` + `event_cluster_items` |
| 评分明细 | `contents.metadata.dimension_scores` | 主要用于解释和回测 | 可继续留在 metadata，按版本归档 |

迁移原则：

- 查询频繁、需要索引、需要跨表 join 的字段，迁移成正式列或表。
- 解释性、版本化、低频读取的字段，继续留在 metadata。
- 每次迁移都保留兼容读取逻辑，避免旧数据不可读。

## 5. 处理流程设计

### 5.1 抓取与正文质量判断

抓取后新增一个轻量质量判定步骤：

1. 读取 `full_content`、`summary`、`translated_summary`、标题、metadata。
2. 判断正文长度、段落数量、重复率、导航文本比例、paywall/error 标记。
3. 写入 `fulltext_status` 和 `content_quality`。
4. 对 `blocked` 或低质量三星源，进入重试或登录态检查队列。

注意：

- 不应为了评分无限打开 Playwright。
- 对需要登录态的网站，只在 auth_ready 的情况下走持久化浏览器上下文。
- 对全文失败的内容，应降低置信度，而不是让模型猜测。

### 5.2 低成本预筛

预筛目标是减少模型调用：

- 标题和摘要是否属于关注领域。
- 是否明显广告、招聘、营销、低信号页面。
- 是否重复抓取。
- 是否低质量短文本。
- 信源 `domain_focus` 是否与内容主题匹配。

可以先用规则和关键词做一版，后续再接便宜模型。

输出：

```json
{
  "prefilter_status": "candidate",
  "prefilter_reason": "AI model launch related",
  "prefilter_score": 0.76,
  "domain_match": 0.82
}
```

### 5.3 模型维度评分

只对 `candidate` 进入维度评分。

输入材料优先级：

1. `full_content`
2. `reader_translated_full_content`
3. `translated_summary`
4. `summary`
5. `title`

模型只输出 JSON，不输出最终选择结论：

```json
{
  "topic_relevance": 0,
  "novelty": 0,
  "impact": 0,
  "authority": 0,
  "actionability": 0,
  "risk": 0,
  "reason_atoms": {
    "why_now": "",
    "why_matters": "",
    "source_context": "",
    "caveat": "",
    "suggested_action": ""
  }
}
```

口径约束（建议写入 schema）：

- 所有维度分为 `0` 到 `10` 的整数。
- `reason_atoms` 任一字段不能为空字符串（允许简短句）。
- 当输入仅有 `title` 时，`impact` 和 `actionability` 默认不高于 `5`，避免臆测。
- 当 `fulltext_status=blocked` 时，模型只允许输出风险与不确定性，不参与高分推荐。

维度建议：

- `topic_relevance`：与用户关注领域的相关性。
- `novelty`：是否为新增事实、首发、重大变化。
- `impact`：潜在影响范围。
- `authority`：信源权威性和证据质量。
- `actionability`：是否值得用户后续阅读、收藏、跟进。
- `risk`：标题党、传闻、低证据、重复信息等风险。

### 5.4 脚本计算最终分

建议新增 `backend/app/services/scoring_service.py`。

示例公式：

```text
base =
  topic_relevance * 0.25 +
  novelty * 0.20 +
  impact * 0.25 +
  authority * 0.15 +
  actionability * 0.15

final_score =
  base * source_weight
  + source_stars_bonus
  + domain_match_bonus
  + multi_source_bonus
  + freshness_bonus
  - low_confidence_penalty
  - risk_penalty
  - duplicate_penalty
```

实现细节建议：

- `base` 先按 0 到 10 口径计算，再统一映射到 0 到 100。
- `final_score` 做上下限截断（`0` 到 `100`），避免极端 bonus/penalty 失真。
- `score_confidence` 与 `final_score` 解耦，前者反映证据充分性，后者反映综合价值。
- 所有 bonus/penalty 要写入可配置项，禁止硬编码散落在业务逻辑中。
- `source_stars_bonus` 必须受 `domain_match` 限制，防止高星但不相关的信源污染精选。

建议初始权重：

| 因子 | 权重或规则 |
| --- | --- |
| topic_relevance | 25% |
| novelty | 20% |
| impact | 25% |
| authority | 15% |
| actionability | 15% |
| 三星 bonus | +6 |
| 二星 bonus | +3 |
| 一星 penalty | -5 |
| domain mismatch penalty | -5 到 -15 |
| summary_only penalty | -8 |
| title_only penalty | -20 |
| blocked penalty | 不进入精选 |
| high risk penalty | -5 到 -20 |

推荐初始阈值：

| 状态 | 条件 |
| --- | --- |
| selected | `final_score >= 75` 且 `score_confidence >= 0.65` |
| candidate | `60 <= final_score < 75` |
| deferred | 全文失败但信源为二星或三星，等待重试 |
| rejected | 低相关、低质量或重复 |

### 5.5 事件聚类

短期方案：增强现有 `RankingService`。

当前 `RankingService` 使用标题和摘要 token/Jaccard 聚类，优点是无外部依赖，缺点是语义聚类弱、跨语言弱、同义表述弱。

短期增强：

- 聚类输入从 `title + summary` 改为 `title + translated_title + summary + translated_summary + score reason`。
- 分数从“长度 + 来源数”改为“内容最终分 + 信源星级 + 多源验证”。
- 主文章选择从“最长标题”改为“官方源优先 + final_score 优先”。
- 对同一来源的重复转载只计一次，不给多源 bonus。

中期方案：引入 embedding。

事件聚类流程：

1. 对候选内容生成 embedding。
2. 在 24 到 72 小时窗口内做近邻检索。
3. 相似度超过阈值则归入已有事件。
4. 未命中则创建新事件。
5. 每次新增内容后更新 cluster score、canonical item、source_count、last_seen_at。

主文章选择规则：

```text
official_blog / official_announcement
> official_social
> paper / repo release
> high-quality media
> KOL
> aggregator
```

事件分数：

```text
cluster_score =
  max(item.final_score)
  + multi_source_bonus
  + source_stars_diversity_bonus
  + canonical_source_bonus
  + freshness_bonus
  - duplicate_penalty
```

聚类结果还需要记录“不确定性”。当相似度不高但标题接近时，应先进入 `candidate_event`，不要直接合并；当高权威来源发布更完整版本时，允许 canonical item 更新，但需要记录变更原因。

## 6. 3 小时报与日报改造

### 6.1 从 HourlyDigest 泛化为 DigestWindow

当前代码里 `compute_digest_window()` 固定计算前 1 小时窗口，`HourlyDigest` 表也以 `digest_date + hour` 做唯一键。

建议分两步：

第一步兼容改造，也就是“窗口频率改造”：

- 继续使用 `HourlyDigest` 表。
- 将任务改成每 3 小时运行一次。
- 标题和正文从“过去 60 分钟”改成“过去 3 小时”。
- `compute_digest_window()` 支持 `window_hours=3`。
- 这一步不强依赖评分链路，可以在 Phase 1 后先做，收益是减少空报告和打扰频率。

第二步结构改造，也就是“事件精选改造”：

新增 `digest_windows` 表：

```text
id
cadence
window_start
window_end
title
summary
content_count
event_count
sources
metadata
created_at
updated_at
```

`cadence`：

- `3h`
- `daily`
- `manual`

这一步应依赖 Phase 2 和 Phase 4 的结果。也就是说，3 小时报可以先从“更长窗口”开始，后续再升级成“基于评分和事件的精选简报”。

### 6.2 3 小时报内容结构

建议结构：

```text
# 过去 3 小时重点

## 最值得关注
1. 事件标题
   推荐理由：...
   来源：三星官方源 + 2 个跟进源

## 快速上升
...

## 值得继续观察
...
```

选择规则：

- 优先事件，不优先单篇文章。
- 每个事件只出现一次。
- 低置信度内容可进入“继续观察”，不要进入“最值得关注”。
- 如果窗口内内容很少，允许不生成完整报告，避免空泛输出。

### 6.3 日报内容结构

建议结构：

```text
# 今日信息简报

## 今日最重要

## 新产品 / 新模型 / 新论文

## 行业动态

## 观点与方法

## 持续发酵

## 明日继续观察
```

日报应该优先使用已经处理好的评分和事件聚类结果，尽量不在日报阶段重新大规模调用模型。

理想路径：

```text
抓取 -> 正文质量 -> 预筛 -> 维度评分 -> 脚本总分 -> 事件聚类 -> 3h / daily deterministic digest
```

## 7. 推荐理由设计

推荐理由应该结构化保存，不只是生成一段自然语言。

建议字段：

```json
{
  "why_now": "为什么现在值得看",
  "why_matters": "为什么重要",
  "source_context": "信源为什么可信或不可信",
  "evidence": "来自正文的关键事实",
  "caveat": "不确定性或风险",
  "suggested_action": "建议收藏、跟进、忽略或进入日报",
  "confidence": 0.84
}
```

前端展示时可以压缩成：

- 推荐理由
- 可信度
- 风险提示
- 来源说明

## 8. 前端改造建议

建议新增或调整几个视图。

### 8.1 精选

展示高分内容和事件：

- 分数
- 信源星级
- 正文状态
- 推荐理由
- 所属事件
- 是否多源验证

### 8.2 全部

保留原始内容流，但增加筛选：

- 信源星级
- 正文状态
- 评分状态
- 是否已入选
- 是否属于事件

### 8.3 事件

以事件为主视图：

- 事件标题
- 主文章
- 相关内容列表
- 来源分布
- 时间线
- cluster_score
- 推荐理由

### 8.4 3 小时报 / 日报

简报应优先展示事件，不只是内容条目。

### 8.5 信源管理

新增信源星级管理：

- source stars
- authority type
- domain focus
- source weight
- noise level
- domain match 历史表现
- 最近抓取质量
- 最近入选率

## 9. 后端模块落点

建议新增或调整：

```text
backend/app/services/content_quality_service.py
backend/app/services/scoring_service.py
backend/app/services/event_cluster_service.py
backend/app/services/digest_window_service.py
backend/app/tasks/scoring_tasks.py
backend/app/tasks/event_cluster_tasks.py
```

改造现有：

```text
backend/app/services/ranking_service.py
backend/app/services/hourly_digest/repository.py
backend/app/services/hourly_digest/selection.py
backend/app/services/hourly_digest/synthesis.py
backend/app/tasks/hourly_digest_tasks.py
backend/app/api/digest.py
backend/app/api/sources/*
backend/app/api/contents*
```

不建议新增一个完全独立的“hotness”系统。应该让评分、聚类、简报都沿现有 PIM pipeline 演进。

## 10. 配置设计

建议在系统设置里新增：

```json
{
  "scoring": {
    "enabled": true,
    "score_version": "pim-score-v1",
    "min_prefilter_score": 0.45,
    "selected_threshold": 75,
    "candidate_threshold": 60,
    "fulltext_required_for_selected": false,
    "weights": {
      "topic_relevance": 0.25,
      "novelty": 0.2,
      "impact": 0.25,
      "authority": 0.15,
      "actionability": 0.15
    },
    "penalties": {
      "summary_only": 8,
      "title_only": 20,
      "domain_mismatch_min": 5,
      "domain_mismatch_max": 15
    }
  },
  "event_clustering": {
    "enabled": true,
    "method": "token",
    "similarity_threshold": 0.28,
    "window_hours": 72
  },
  "digest_windows": {
    "three_hour_enabled": true,
    "daily_enabled": true,
    "three_hour_interval": 3,
    "max_events_per_digest": 8
  }
}
```

## 11. 实施路线

### 11.0 里程碑与 Go/No-Go Gate

每个 Phase 结束都应做一次 Gate 审查，避免“功能已做完但效果不可证”的情况。

| Gate | 必须满足 | 未达标处理 |
| --- | --- | --- |
| G0（Phase 0 后） | baseline 数据可复现，样本集可用于回测 | 补齐数据口径和样本定义，不进入 Phase 1 |
| G1（Phase 1 后） | `fulltext_status` 覆盖新内容，source 星级覆盖率达标 | 继续补标并修正抓取质量判定 |
| G2（Phase 2 后） | 评分链路稳定，无阻塞，解释字段完整 | 暂缓基于评分的精选简报，先修评分稳定性 |
| G3（Phase 3 后） | 3 小时报质量指标优于旧小时报 | 保留旧任务并回滚窗口策略 |
| G4（Phase 4 后） | 事件折叠有效，重复事件显著下降 | 继续使用增强版 `RankingService`，暂缓新表 |
| G5（Phase 5/6 后） | 日报稳定、反馈可用于调参 | 停止扩功能，优先做质量闭环 |

### Phase 0：准备与基线

目标：建立可回测的现状基线。

任务：

- 导出最近 7 天内容样本。
- 标记当前全文可用率、摘要可用率、各 source 类型数量。
- 统计当前小时报平均内容数、空报告比例、重复事件比例。
- 定义评分 JSON schema。

验收：

- 有一份 baseline 报告。
- 有 20 到 50 条人工标注样本，作为评分回测集。

### Phase 1：信源星级与全文状态

目标：让系统知道“来源质量”和“正文质量”。

任务：

- 在 Source metadata 增加 `source_stars`、`authority_type`、`source_weight`。
- 在 Content metadata 增加 `fulltext_status`、`content_quality`、`score_basis`。
- 增加抓取后质量判断函数。
- 前端 source 列表展示星级。
- 内容详情展示正文状态。

验收：

- 新抓取内容都带 `fulltext_status`。
- 至少 80% source 有初始星级。
- blocked/summary_only/title_only 可被筛选出来。

### Phase 2：维度评分与脚本总分

目标：模型打维度分，脚本算最终分。

任务：

- 新增 `scoring_service.py`。
- 定义模型 JSON 输出 schema。
- 对 candidate 内容生成 `dimension_scores`。
- 用脚本计算 `final_score`、`score_confidence`、`selection_status`。
- 保存 `score_version`。
- 增加回测脚本。

验收：

- 最近 100 条内容有评分结果。
- 能按 `final_score` 排序。
- 能解释每条 selected 内容为什么入选。
- 评分失败不会阻塞抓取。

说明：G2 约束的是“基于评分的精选简报”。如果只是把小时报窗口从 1 小时改为 3 小时，可以在 G1 后先做灰度，不必等待完整评分链路。

### Phase 3：3 小时报

目标：替代过短的小时报。

任务：

- `compute_digest_window()` 支持 3 小时窗口。
- scheduler 从每小时改为每 3 小时，或保留任务但只在 0/3/6/9/12/15/18/21 点生成。
- 标题、空状态文案、API schema 更新为 3 小时报。
- 前端导航从“小时报”改为“3 小时报”。
- 先保证窗口正确，再逐步接入评分和事件聚类。

验收：

- 3 小时报覆盖过去 3 小时。
- 空报告比例下降。
- 简报条目以高分候选为主。
- 如果评分链路尚未稳定，允许先使用增强版 `RankingService` 作为过渡选择器。

### Phase 4：事件聚类

目标：把重复文章折叠成事件。

任务：

- 先增强现有 `RankingService`。
- 聚类分数纳入 `final_score` 和 `source_stars`。
- 主文章选择支持官方源优先。
- 保存 event_key 到 content metadata。
- 稳定后新增 `event_clusters` 表。

验收：

- 同一事件的重复报道能被折叠。
- 3 小时报中同一事件只出现一次。
- 事件能展示相关来源。

### Phase 5：日报重构

目标：日报基于事件和评分生成，不再只是按类型列内容。

任务：

- 日报从当日 selected/candidate events 构建。
- 增加栏目：今日最重要、产品/模型/论文、行业动态、观点方法、持续发酵、继续观察。
- 日报生成尽量使用已有结构化数据，减少新模型调用。

验收：

- 日报能稳定输出 5 到 12 个高质量事件。
- 每个事件都有推荐理由。
- 多源事件优先级合理。

### Phase 6：反馈闭环

目标：让系统越用越准。

任务：

- 前端增加反馈：有用、无用、重复、太泛、漏掉重点。
- 保存用户反馈。
- 回测不同 score_version。
- 调整脚本权重，不优先膨胀 prompt。

验收：

- 能查看 selected 内容的命中率。
- 能比较不同评分版本。
- 能基于反馈调整权重。

## 12. 测试计划

### 单元测试

- `content_quality_service`：不同正文长度、paywall、summary-only、title-only 判断。
- `scoring_service`：公式、阈值、降权、版本。
- `event_cluster_service`：同事件聚合、不同事件分离、主文章选择。
- `digest_window_service`：3 小时窗口、日报窗口、时区边界。

### 集成测试

- 抓取后内容自动写入全文状态。
- 评分失败不影响抓取入库。
- 3 小时报只取窗口内内容。
- 日报不重复展示同一事件。
- 三星源在主文章选择中优先。

### 回测

- 最近 7 天内容。
- 最近 30 天高频信源。
- 人工挑选 50 条“应该入选”和“应该排除”的样本。
- 每个星级至少覆盖 10 条样本，避免评分只对高星源有效。
- 每种正文状态至少覆盖 10 条样本，尤其要覆盖 `blocked` 和 `summary_only`。

### 监控与告警（新增）

建议将以下指标接入现有 metrics 体系，并配置基础告警：

- 抓取质量：`fulltext_status` 分布、`blocked` 比例、auth 失败率。
- 评分质量：评分成功率、平均 `score_confidence`、高分内容占比异常波动。
- 聚类质量：单窗口重复事件率、平均事件包含文章数、canonical 变更频率。
- 简报质量：3 小时报空报告率、日报事件数分布、生成耗时、失败重试次数。
- 成本指标：模型调用次数、token 消耗、按信源类型分摊成本。

建议告警阈值：

- 连续 3 个窗口空报告率 > 60%。
- `blocked` 比例较 7 日均值上升 2 倍以上。
- 评分失败率连续 30 分钟 > 5%。

## 13. 风险与约束

### 13.1 付费墙与登录态

PIM 可以使用用户已经授权保存的登录态去访问用户可访问的内容，但不应设计为绕过付费墙或规避网站访问控制的工具。工程上要做的是：

- 明确 `auth_ready` 状态。
- 明确 `blocked` / `paywall_detected`。
- 不对不可见正文进行高置信度评分。
- 不因为全文失败反复启动浏览器造成资源占用。

### 13.2 模型成本

不要对所有内容都做深度模型评分。

控制策略：

- 规则预筛。
- 只对 candidate 评分。
- 只对 selected/candidate 进入聚类增强。
- 日报复用已有结构化结果。
- 保存 score_version，避免无意义重复评分。

### 13.3 资源占用

此前 PIM 的资源问题说明，全文抓取和 Playwright 必须谨慎：

- 限制浏览器并发。
- 登录态失效时不要继续走持久化浏览器。
- 对一星或低匹配信源不要默认深度抓取全文。
- 对二星和三星源才允许更积极重试。

同时建议把评分和抓取解耦：

- 抓取任务只负责入库和正文质量标记。
- 评分任务异步运行，失败后写入 `scoring_error`，不重试抓取。
- 批量评分要设置每轮上限，避免历史数据回填时抢占正常抓取资源。

### 13.4 数据合规与隐私

推荐理由和事件摘要可能包含个人信息或受限内容，需要最小化存储与展示范围：

- 仅保存与推荐决策相关的必要字段，避免无边界落库原文片段。
- 为导出、API 返回增加字段级开关，支持隐藏敏感 evidence。
- 对外展示优先摘要化表述，不回显潜在受限全文。
- 为后续审计保留评分链路日志（版本、权重、输入来源），不保留不必要明文。

## 14. 推荐优先级

最推荐先做：

1. Source stars metadata。
2. Content fulltext status。
3. Dimension score JSON schema。
4. Scoring service 公式。
5. 3 小时报窗口。
6. metadata 到正式列/表的迁移条件。

原因：

- 这些是后续事件聚类和日报重构的地基。
- 改动可控。
- 不需要一开始引入 embedding 或新表。
- 可以很快验证精选质量是否变好。

暂缓：

- 复杂 embedding 聚类。
- 大规模数据库迁移。
- 完整事件详情页。
- 复杂趋势预测。

这些应该等评分和 3 小时报稳定后再做。

## 15. 本次修订后的执行建议

建议按“先稳定评分链路，再提升聚类语义，再扩展展示体验”的顺序推进，优先拿到可验证收益：

1. 先完成 Phase 0 到 Phase 2，并通过 G2 Gate。
2. 3 小时报窗口可以在 G1 后先灰度，基于评分的精选简报等 G2 后再接入。
3. 在 G2 通过前，不做 embedding 或新事件表迁移。
4. 用 14 天滚动指标评估改造效果，避免单日波动误导决策。
5. 所有阈值、bonus、penalty 配置化并版本化，确保可回滚。
6. 每个阶段结束都更新一页“结果面板”（质量、成本、稳定性三类指标）。

## 16. 一句话总结

PIM 的升级方向应是：全文优先但不阻塞，模型只给维度分，脚本负责最终判断，事件替代重复文章，3 小时报和日报替代过短小时报，推荐理由结构化保存并在前端展示。
