# pim-score-v2.3 运维与升级指南

本文说明 PIM 内容评分模型（`pim-score-v2.3`）的结构、配置入口、调试方法与版本升级步骤。

**相关代码**

| 模块 | 路径 |
|------|------|
| 词表（lane / 实体 / 事件模式） | `backend/app/domains/score/score_vocab.py` |
| 规则维打分 | `backend/app/domains/score/score_rules.py` |
| 主观分接口（LLM 预留） | `backend/app/domains/score/score_subjective.py` |
| 单篇合分 | `backend/app/domains/score/scoring.py` |
| 事件层（热点 + 多源） | `backend/app/domains/score/score_event.py` |
| 简报聚类排序 | `backend/app/domains/score/ranking.py` |
| 抓取验收（打分前置） | `backend/app/domains/fetch/acceptance.py` |
| 摘要 boilerplate 清洗 | `backend/app/domains/ingest/summary_clean.py` |
| 设计规格 | `docs/superpowers/specs/2026-05-21-pim-score-v2-design.md` |

---

## 1. 模型概览

### 1.0 评分总词表 = 静态词表 + 用户关键词

| 层 | 来源 | 作用 |
|----|------|------|
| **静态词表** | `score_vocab.py`（代码） | 全球通用的 lane / 实体 tier / 事件 pattern |
| **用户关键词** | `keywords` 表（UI 维护） | 合并进运行时 **entity tier B**；命中时显著性不低于 A 档 |

实现：`score_vocab_runtime.py` 在 finish 打分前读取所有已启用关键词（含等价词），与静态 tier 合并；`keyword_matches` 中实际命中的词会抬高 `salience`。

metadata 可追溯字段：

- `score_vocab_user_terms` — 当前生效的用户词表子集
- `score_vocab_matched_user_terms` — 本篇命中的用户词

关键词仍负责 **高亮 / 告警 / 可选入库过滤**；与评分共用同一套词，不再两套平行列表。

### 1.1 流水线

```text
抓取 → ingest finish → 摘要清洗 → fetch 验收 → 单篇 article_score → 小时报聚类 → event_score
```

- **摘要清洗**（`summary_clean.py`）：在打分前去掉 RSS/通讯 boilerplate（如 The Verge *Regulator* 订阅引导、「阅读全文」尾句），避免误触发 commerce 降权。翻译路径同样先洗后译。
- **fetch 验收失败**：写入 `fetch_acceptance=incomplete`，**不计算** `article_score`。
- **fetch 验收通过**：写入 `score_version=pim-score-v2.3` 与五维 `dimension_scores`。
- **Website/RSS 最低门槛**：标题 + 有效摘要 ≥50 字；正文状态可为 `full` / `partial` / `summary_only`（RSS 仅摘要也可打分，置信度较低）。摘要取 **原文与译文较长者**，避免译文过短误拒。

### 1.2 单篇分（article_score，0–100）

| 维度 | 权重 | 实现 |
|------|------|------|
| salience 显著性 | 30% | 规则 |
| reach 影响面 | 25% | 规则；S-tier 实体无 sector 关键词时给 6.5（major_entity 子桶） |
| authority 信源权威 | 25% | 规则 |
| depth 信息深度 | 20% | 规则 |
| subjective 主观 | 0%（Shadow） | 设置页 `ai_subjective_scoring_enabled` 开启后接入 `LlmSubjectiveScorer` |

`final_score` 与 `article_score` 相同（兼容旧 UI）。  
`scoring_method` 为 `"rule"`（纯规则）或 `"rule+llm-shadow"`（命中 LLM Shadow）。

**入选阈值（默认）**

| selection_status | 条件 |
|------------------|------|
| `selected` | article_score ≥ 70，且 score_confidence ≥ 0.65 |
| `candidate` | 55 ≤ score < 70，或 score ≥ 70 但 confidence 不足 |
| `rejected` | score < 55 |

`confidence_limited_by_fulltext=true` 表示分数达到入选线但被置信度拦截（通常因 `fulltext_status=title_only`）。

### 1.3 Lane 分类

`lane` 表示文章的首要叙事对象；后端 `/api/score-lab/lanes` 是前后端共享的唯一枚举契约。

| lane | 中文 | English |
|------|------|---------|
| `domestic_politics` | 国内时政 | Domestic Politics |
| `public_safety` | 公共安全 | Public Safety |
| `geopolitics` | 地缘外交 | Geopolitics & Diplomacy |
| `macro_economy` | 宏观经济 | Macroeconomy |
| `macro_finance` | 宏观金融 | Macro Finance |
| `markets` | 市场交易 | Financial Markets |
| `regulation` | 监管政策 | Regulation & Policy |
| `industry_news` | 行业新闻 | Industry News |
| `company_news` | 公司新闻 | Company News |
| `product_news` | 产品新闻 | Product News |
| `vc_deals` | 创投融资 | Venture Capital & Funding |
| `public_figures` | 公共人物 | Public Figures |
| `other` | 其它 | Other |

### 1.4 语料范围（避免正文误伤）

| 维度 / 检测 | 扫描范围 |
|-------------|----------|
| salience / reach | **标题 + 摘要**（`translated_*` 优先） |
| depth / lane 辅助 | 标题 + 摘要 + 正文前 800 字 |
| commerce / narrow 降权 | **标题 + 摘要**（headline corpus） |
| 灾害显著性下限 | 标题 + 摘要 |

打分标题：`scoring_title()` 优先 `translated_title`，否则 `title`。

### 1.5 低影响故事降权（impact caps）

命中 `COMMERCE_SIGNALS` 或 `NARROW_SCOPE_SIGNALS` 时，对 salience / reach / depth 设上限（`score_vocab.py` → `IMPACT_CAPS`）：

| 桶 | 典型场景 | salience | reach | depth |
|----|----------|----------|-------|-------|
| `commerce` | 促销、配件评测、订阅引导 fluff | ≤ 3.5 | ≤ 3.5 | ≤ 4.0 |
| `narrow` | 人事任命、小配件、上手评测 | ≤ 6.5 | ≤ 5.5 | ≤ 7.5 |

**豁免**：headline 含 IPO / 公开募股等 `MARKET_OFFERING_EXEMPT` 术语时不走 commerce 桶（避免「stock sale」误伤 SpaceX IPO 等）。

commerce 信号在 **标题或摘要** 任一命中即生效；摘要里的订阅 boilerplate 应在上游清洗，而非缩小匹配范围。

### 1.6 灾害显著性下限

标题同时含灾害词（`DISASTER_TERMS`）与伤亡词（`CASUALTY_TERMS`）→ salience ≥ 9.0。  
标题含灾害 + 摘要/标题含多区域词 → reach 可按 systemic（9.0）处理。

### 1.7 事件分（event_score，简报排序）

```text
event_score = 0.50 × max(article_score)
            + 0.30 × momentum × 10
            + 0.20 × corroboration × 10
```

- **momentum**：簇大小 + 近 6h 新发（对数）
- **corroboration**：按 **`source_id`** 独立源计数（首版不通稿去重）

| tier | 条件 | 分 |
|------|------|-----|
| strong | ≥3 独立 source_id | 9.0 |
| moderate | 2 独立 source_id | 6.5 |
| single_high | 1 源且 ≥3 星或 official | 5.5 |
| single_low | 其余 | 2.5 |

---

## 2. metadata 字段

### 单篇（`contents.metadata_`）

```json
{
  "fetch_acceptance": "accepted",
  "score_version": "pim-score-v2.3",
  "scoring_method": "rule",
  "lane": "product_news",
  "dimension_scores": {
    "salience": 9.0,
    "reach": 9.0,
    "authority": 8.5,
    "depth": 7.2,
    "subjective": 5.0
  },
  "subjective_meta": {
    "score": 5.0,
    "source": "fixed_baseline",
    "rationale": null,
    "model": null
  },
  "article_score": 82.4,
  "final_score": 82.4,
  "selection_status": "selected",
  "recommendation_reason": { "...": "..." }
}
```

### 事件簇（digest 内存结构，不写回 DB）

`app.domains.score.ranking.RankingService.cluster_and_rank` 返回：`event_score`, `momentum`, `corroboration`, `corroboration_tier`, `independent_source_count`。

---

## 3. 日常调参

### 3.1 调整赛道 / 实体 / 事件关键词

编辑 **`score_vocab.py`**（按领域分组，末尾 `_merge` 去重合并）：

- `LANE_KEYWORDS` / `_GEO_TERMS` 等 — 赛道分类术语
- `ENTITY_TIER_S/A/B` — 来源 `_GEO_LEADERS_S`、`_TECH_COMPANIES_S` 等子表
- `EVENT_PATTERNS` — 事件类型加成
- `REACH_KEYWORDS` — 影响面形状

子表覆盖时政人物/机构、央行与华尔街、科技巨头与 AI 实验室、常见财经/监管/市场术语。按需增删单行即可，不必改打分逻辑。

改完后跑：

```bash
cd backend && .venv/bin/python -m pytest tests/test_score_v2_rules.py -q
```

### 3.2 调整权重与入选阈值

编辑 **`scoring.py`** 中 `ScoringConfig`：

- `weights` — 五维权重（总和应为 1.0；subjective 当前为 0）
- `selected_threshold` / `candidate_threshold` — 默认 70 / 55

### 3.3 调整事件层公式

编辑 **`score_event.py`**：

- `compute_momentum` — 时间窗与对数系数
- `compute_corroboration` — 分档阈值
- `compute_event_score` — 三项权重（默认 50/30/20）

### 3.5 调整 commerce / narrow / 灾害词表

编辑 **`score_vocab.py`**：

- `COMMERCE_SIGNALS` — 促销、订阅 fluff、小配件等
- `NARROW_SCOPE_SIGNALS` — 人事、评测、外设
- `MARKET_OFFERING_EXEMPT` — IPO 等不应被 commerce 误伤
- `DISASTER_TERMS` / `CASUALTY_TERMS` — 灾害下限
- `IMPACT_CAPS` — 各桶分数上限

### 3.6 调整摘要清洗规则

编辑 **`summary_clean.py`** 中 `_BOILERPLATE_MARKERS` / `_PAYWALL_TAIL`。  
改完后跑 `tests/test_summary_clean.py`。

### 3.7 信源权威

在信源 `metadata_` 中配置：

- `source_stars`：1–3
- `authority_type`：`official` | `regulator` | `wire` | `primary`（可选）

---

## 4. 启用 LLM 主观分

在「设置 → AI 模型」配置 `score_model` 并开启「AI 主观评分」。旧环境变量
`PIM_SCORE_LLM_SUBJECTIVE` 只参与一次性升级迁移，不是运行时开关。

实现入口：`score_subjective.py`

- `resolve_subjective_score()` — finish 同步路径，永远返回 fixed_baseline（LLM 为纯异步）
- `score_subjective_async()` — 先校验 fetch acceptance、正文状态和 URL 标题，再解析统一 policy
- `LlmSubjectiveScorer` — 只发送标题、可靠摘要和最多 800 字正文补充；`max_tokens ≤ 150`
- `ai_subjective_score_cache` — 按 input hash、provider/model version、prompt version 幂等复用，缓存命中不重复调用或占预算
- `merge_rule_scoring_metadata_async()` — 仅写入 Shadow metadata 和 `scoring_method=rule+llm-shadow`

启用且调用成功后，metadata 中 `subjective_meta.source` 为 `llm`，并填充
模型、Prompt、输入范围、Token/成本和 `rationale`；`scoring_method` 变为
`rule+llm-shadow`。

**注意：** subjective 权重固定为 0%。本阶段禁止因开启 Shadow 改变
`article_score`、`final_score`、`selection_status` 或排序；调整权重必须另立 PRD。

---

## 5. 调试

### 5.1 查看单篇打分

SQL（SQLite）：

```sql
SELECT id, title,
       json_extract(metadata_, '$.score_version') AS ver,
       json_extract(metadata_, '$.lane') AS lane,
       json_extract(metadata_, '$.article_score') AS score,
       json_extract(metadata_, '$.dimension_scores') AS dims,
       json_extract(metadata_, '$.fetch_acceptance') AS fetch_ok
FROM contents
ORDER BY fetched_at DESC
LIMIT 20;
```

### 5.2 为何没有分数

| 现象 | 原因 |
|------|------|
| 无 `final_score` | `fetch_acceptance=incomplete`，见 `fetch_incomplete_reason` |
| `subjective` 恒为 5 | 正常；LLM 主观分未启用 |
| 简报排序与 Dashboard 不一致 | 简报用 **event_score**（含多源），Dashboard 用 **article_score** |

### 5.3 单元测试

```bash
cd backend
.venv/bin/python -m pytest tests/test_score_v2_rules.py tests/test_content_quality_scoring.py \
  tests/test_fetch_acceptance.py tests/test_hourly_digest_ranking.py -q
```

---

## 6. 批量重打分（历史回填）

词表或规则变更后，对库内已有文章重算分数：

```bash
cd backend
.venv/bin/python scripts/rescore_contents.py          # 全量提交
.venv/bin/python scripts/rescore_contents.py --dry-run  # 试跑不落库
.venv/bin/python scripts/rescore_contents.py --limit 50
```

脚本会：清洗 summary → 清除旧 `score_version` 缓存 → 重新 fetch 验收 → 调用 `merge_baseline_scoring_metadata`。  
前端 Dashboard / 内容列表读取 `metadata.final_score`（与 `article_score` 相同），重跑后刷新页面即可。

如果只需要迁移 lane、不希望改变既有分数和 selection status：

```bash
cd backend
.venv/bin/python scripts/reclassify_content_lanes.py          # 默认 dry-run
.venv/bin/python scripts/reclassify_content_lanes.py --apply  # 审阅转换统计后提交
```

**注意**：修改 `score_vocab.py` / `score_rules.py` / `summary_clean.py` 后需 **重启后端** 使新 ingest 路径生效；历史行需跑本脚本。

---

## 7. 版本升级 checklist（v2 → v3）

1. **定版**：更新 `SCORE_VERSION`（`scoring.py`），写迁移说明。
2. **词表**：复制/扩展 `score_vocab.py`，保留旧版快照便于对比。
3. **兼容**：digest / ranking 对旧行回退读 `final_score`（当前已支持）。
4. **回填**：`backend/scripts/rescore_contents.py` 批量重算（见 §6）。
5. **测试**：跑 `test_score_v2_rules.py` + 平衡锚点（地缘 vs 科技）。
6. **文档**：更新本文与 `docs/superpowers/specs/` 下规格。
7. **前端**：若维度名变更，同步 `dashboardUtils.ts` 与 selection catalog 文案。

---

## 8. 已知限制（v2.3）

- 不通稿 / 转载去重（多源可能高估）
- 无 personal_fit、freshness 维
- subjective 权重归零；LLM scorer 仅处理合格 saved/实质 updated，并受持久缓存、并发 2 和预算约束（见 §4）
- lane / salience 为关键词规则，复杂语义需 LLM 主观分或后续 entity 库

---

## 9. 变更记录

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-07-30 | pim-score-v2.3 | lane 扩展为 13 类；拆分国内时政/公共安全、宏观经济/金融、行业/公司/产品；前后端改用共享 API 契约 |
| 2026-05-24 | pim-score-v2.2 | subjective 权重归零（0%）；阈值调整 70/55；reach major_entity 子桶（6.5）；词边界保护；用户词扫描范围扩至 2000 字；中文 trigram；LlmSubjectiveScorer 实装；ingest score shim 清除 |
| 2026-05-21 | pim-score-v2.1 | 固化：commerce/narrow impact caps、灾害下限、headline 语料、摘要清洗、`rescore_contents.py` |
| 2026-05-21 | pim-score-v2 | 规则五维 + 固定主观分；fetch 验收与打分分离；事件层 corroboration |
