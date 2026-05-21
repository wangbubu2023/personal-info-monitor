# pim-score-v2 设计规格

**状态：** 已实现（2026-05-21）  
**替代：** `pim-score-v1`（`backend/app/domains/ingest/scoring.py`）  
**前置：** fetch 验收（`fetch_acceptance`）已在 finish 阶段与价值打分分离。

---

## 目标

1. 单篇打分反映 **赛道内显著性**，不内置「地缘政治 > 行业突破」的全球偏见。  
2. **多源印证**在 12h 事件层计算，第一版仅按 `source_id` 去重（不做通稿折叠）。  
3. **规则为主**实现 salience / reach / lane / authority / depth；**LLM 主观分**预留接口，当前写入固定中性分。  
4. 暂不做：personal_fit（个人相关）、freshness（时效）、通稿去重。

---

## 两层分数

```
finish（单篇）          digest 窗口（12h）
─────────────────      ─────────────────────────
fetch 验收通过    →    相似度聚类
article_score     →    momentum + corroboration
                       → event_score（简报排序主信号）
```

| 字段 | 层级 | 用途 |
|------|------|------|
| `article_score` | 单篇 | Dashboard、簇内选代表稿 |
| `event_score` | 事件簇 | 小时报排序、入选重点 |
| `final_score` | 兼容 | v2 起等于 `article_score`，保留字段名减少前端改动 |

---

## 单篇维度（article_score）

### 权重

| 维度 | key | 权重 | 首版实现 |
|------|-----|------|----------|
| 显著性 | `salience` | 25% | 规则 |
| 影响面 | `reach` | 20% | 规则 |
| 信源权威 | `authority` | 20% | 规则 |
| 信息深度 | `depth` | 15% | 规则 |
| 主观判断 | `subjective` | 20% | **固定 5.0**（LLM 接口预留） |

合分（0–100）：

```text
base_0_10 = Σ (dimension_i × weight_i)   # 各维 0–10
article_score = round(clamp(base_0_10 × 10, 0, 100), 2)
```

`subjective` 首版恒为 **5.0**，等价于每篇贡献 `5 × 0.20 × 10 = 10` 分基准线；接入 LLM 后只替换该维数值，权重不变。

### 赛道 lane（规则分类）

用于 **salience 校准**，不做跨赛道高低比较。

| lane | 说明 | 关键词示例（标题+摘要+正文前 800 字） |
|------|------|--------------------------------------|
| `geopolitics` | 地缘、外交、军事 | 访华、制裁、联合国、NATO、台海 |
| `macro_finance` | 宏观、央行、利率 | 美联储、降息、CPI、国债 |
| `regulation` | 监管、立法 | 反垄断、FDA、SEC、网信办 |
| `tech_product` | 科技产品、模型、平台 | OpenAI、模型、发布、API、芯片 |
| `markets` | 市场、交易 | 股价、财报、并购、IPO |
| `corporate` | 公司动态（非产品级） | 裁员、CEO 任命、合作 |
| `vc_deals` | 融资、投资 | 融资、A 轮、估值 |
| `other` | 未命中 | 默认 |

**分类算法：** 对每条 lane 统计 keyword hit score（长词优先、标题命中 ×2），取得分最高 lane；最高分 `< 1` 则 `other`。

### salience（赛道内显著性，0–10）

在 lane 内用 **entity tier + event pattern** 规则打分，取两者较高值（封顶 10）。

**Entity tier（主体层级）**

| tier | 分 | 规则示例 |
|------|-----|----------|
| S | 9.0 | 中美俄元首/首脑；G7 央行；FAANG+OpenAI/Anthropic 级 |
| A | 7.5 | 各国部长/州长；标普100；主流 AI 实验室 |
| B | 6.0 | 垂直龙头、知名 KOL |
| C | 4.0 | 默认 / 未识别主体 |

实体表首版维护在 `backend/app/domains/ingest/score_vocab.py`（可扩展 JSON/DB）。

**Event pattern（事件类型加成）**

| pattern | +分 | 关键词 |
|---------|-----|--------|
| summit_visit | +1.0 | 访华、峰会、会晤 |
| model_release | +1.0 | 发布模型、新模型、GPT |
| policy_shift | +1.0 | 法案、禁令、全面 |
| earnings | +0.5 | 财报、营收 |
| funding | +0.5 | 融资、亿美元 |

```text
salience = min(10, max(entity_tier_score, entity_tier_score + pattern_bonus))
```

**平衡原则：** `geopolitics` 与 `tech_product` 的 S 级都映射到 9.0，不做「国家 > 公司」跨 lane 扣分。

### reach（影响面类型，0–10）

不问「影响地球多少人」，问 **冲击形状**（各 lane 共用枚举）：

| reach | 分 | 规则信号 |
|-------|-----|----------|
| `systemic` | 9.0 | 全面、所有、全球、行业格局、系统性 |
| `sector` | 7.0 | 行业、赛道、生态、供应链 |
| `entity` | 5.5 | 默认；单公司/单人 |
| `local` | 3.5 | 当地、区域、试点 |

Trump 访华 → 常命中 `systemic`（9.0）；OpenAI 新模型 → `systemic` 或 `sector`（9.0 / 7.0），可同台比较。

### authority（信源权威，0–10）

```text
authority = source_stars_base + authority_type_bonus
```

| source_stars | base |
|--------------|------|
| 3 | 8.5 |
| 2 | 6.5 |
| 1 | 4.0 |

| authority_type（metadata） | bonus |
|------------------------------|-------|
| official / regulator | +1.0 |
| wire / primary | +0.5 |
| （缺省） | 0 |

封顶 10。**取消** v1 的 `source_stars_bonus` 加减分，避免重复计分。

### depth（信息深度，0–10）

基于 fetch 验收后的正文（非抓取质量）：

```text
depth = clamp(structure + fact_density + type_adjust, 0, 10)
```

| 信号 | 计算 |
|------|------|
| structure | min(4, paragraph_count × 0.8) |
| fact_density | min(4, digit_count×0.3 + quote_markers×0.5) |
| type_adjust | X 短帖：+2；X 长文/website full：+1；partial：0 |

X 短帖（`content_type=x` 且非 long article）不 penalize 长度。

### subjective（主观分，0–10）— 预留

**首版（固定）：**

```python
SubjectiveScoreResult(
    score=5.0,
    source="fixed_baseline",
    rationale=None,
    model=None,
)
```

**预留接口：**

```python
# backend/app/domains/ingest/score_subjective.py

class SubjectiveScorer(Protocol):
    async def score(self, content: Content, *, lane: str) -> SubjectiveScoreResult: ...

def get_subjective_scorer() -> SubjectiveScorer:
    if settings.PIM_SCORE_LLM_SUBJECTIVE_ENABLED:
        return LlmSubjectiveScorer(...)
    return FixedBaselineSubjectiveScorer(score=5.0)
```

LLM 实现后续输出：`score`、`rationale`、`model`；`source="llm"`。  
finish 流程 **同步路径**先用 `FixedBaselineSubjectiveScorer`；LLM 版可走 async sidecar 回填 metadata（与 atoms 类似），不阻塞 ingest。

---

## 事件层（event_score）

在 `RankingService.cluster_and_rank` 之后，对每个 cluster 计算。

### momentum（0–10）

```text
momentum = min(10, 2.5 × log2(1 + cluster_size) + recent_bonus)
recent_bonus = min(2, count(publish_time in last 6h) × 0.5)
```

### corroboration（0–10）

**独立源：** 簇内 distinct `source_id`（首版不做通稿折叠）。

| tier | 条件 | 分 |
|------|------|-----|
| strong | ≥3 独立 source_id | 9.0 |
| moderate | 2 独立 source_id | 6.5 |
| single_high | 1 源且 max(stars)≥3 或 authority_type=official | 5.5 |
| single_low | 其余 | 2.5 |

**独家保护：** `single_high` 不被当作「待证实谣言」压到 bin 底。

### event_score 合分

```text
event_score = round(
    0.50 × max(article_score in cluster)
  + 0.30 × momentum
  + 0.20 × corroboration × 10   # corroboration 已是 0-10
, 2)
```

写入 cluster dict：`event_score`, `corroboration_tier`, `independent_source_count`, `momentum`.

---

## metadata 形状

```json
{
  "score_version": "pim-score-v2",
  "scoring_method": "rule",
  "lane": "tech_product",
  "dimension_scores": {
    "salience": 9.0,
    "reach": 9.0,
    "authority": 8.5,
    "depth": 7.2,
    "subjective": 5.0
  },
  "subjective_meta": {
    "source": "fixed_baseline",
    "rationale": null,
    "model": null
  },
  "article_score": 82.4,
  "final_score": 82.4,
  "selection_status": "selected",
  "recommendation_reason": { "...": "规则生成，引用 lane + corroboration 待 digest 补充" }
}
```

digest 阶段 cluster 附加：

```json
{
  "event_score": 88.1,
  "corroboration_tier": "strong",
  "independent_source_count": 4,
  "momentum": 7.5
}
```

---

## selection_status（单篇）

沿用 v1 阈值思路，基于 `article_score`：

| 状态 | 条件 |
|------|------|
| selected | article_score ≥ 75 |
| candidate | article_score ≥ 60 |
| rejected | < 60 |

`fetch_acceptance=incomplete` 仍跳过全部 scoring（与 v1 后改一致）。

---

## 文件规划

| 文件 | 职责 |
|------|------|
| `backend/app/domains/ingest/score_vocab.py` | lane 关键词、entity tier、event pattern |
| `backend/app/domains/ingest/score_rules.py` | 规则维打分纯函数 |
| `backend/app/domains/ingest/score_subjective.py` | SubjectiveScorer 协议 + FixedBaseline |
| `backend/app/domains/ingest/scoring.py` | 改为 v2 入口：`calculate_article_score`, `merge_rule_scoring_metadata` |
| `backend/app/services/ranking_service.py` | corroboration / momentum / event_score |
| `backend/tests/test_score_v2_rules.py` | 规则与平衡用例（Trump vs OpenAI） |

---

## 测试锚点

1. **lane 平衡：** 特朗普访华 vs OpenAI 新模型 → 同 tier 配置下 `salience` 均 ≥8.5，无系统性一方被压。  
2. **X 短帖：** depth 不因字数短而 <4。  
3. **corroboration：** 3 个 source_id → strong；1 个 3 星 → single_high。  
4. **subjective 固定：** 未开 LLM 时 `subjective=5.0`, `source=fixed_baseline`。  
5. **fetch 失败：** 仍无 `article_score`。

---

## 迁移

- 新入库：`score_version=pim-score-v2`。  
- 旧行：保留 v1 metadata；digest 排序优先读 v2，无则回退 v1 `final_score`。  
- 可选 admin 任务：批量重算 v2（非首版必须）。

---

## 明确不做（v2.0）

- 通稿 / AP 转载去重  
- personal_fit、freshness  
- LLM 主观分（仅接口 + 固定 5.0）  
- risk 维（保留为 v2.1 修饰项讨论）

---

## 实现顺序

1. `score_vocab` + `score_rules` + 单测（含平衡锚点）  
2. `score_subjective` 固定实现 + finish 接入  
3. `scoring.py` v2 合分，替换 baseline v1  
4. `RankingService` event 层  
5. selection catalog 展示 lane / corroboration  
