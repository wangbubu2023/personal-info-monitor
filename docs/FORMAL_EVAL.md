# Formal Eval 与质量闭环

M2 将 Day-0 Bootstrap 与正式发布评测分成两个不可混用的 tier：

| Tier | 最低数据 | 用途 |
|---|---:|---|
| `bootstrap` | Core 50；Event 15 簇/50 pair | M0/M1 正确性、迁移与评测链路 |
| `formal_eval_1_0` | Core 200；Event 50 簇/200 pair | 评分、排序、Event membership 与 Today 切换门禁 |

Bootstrap 通过不授权算法或 UI 切换。正式数据缺失、hash 不匹配、人工标签缺失或数据集含预填 prediction 时，门禁失败。

## 1. 数据安装

Core 数据与 manifest：

- `backend/tests/fixtures/core_eval_1_0.jsonl`
- `backend/tests/fixtures/core_eval_1_0_manifest.json`

Core 每条记录必须带人工 `label`，并覆盖 `source_type`、`language`、`paywall`、`content_length`、`case_type` 五个 strata。数据集不得出现 `prediction`、`predicted_score`、`article_score`、`final_score` 或 `score`；运行器会调用当前真实 scoring pipeline 重新生成预测。

生产候选导出必须使用 formal 模式，以免把现有分数带入标签集：

```bash
cd backend
uv run python scripts/export_eval_candidates.py \
  --formal --limit 500 --min-records 200 --max-days 365 \
  --output ~/.pim/data/core_eval_1_0_candidates.jsonl
```

Event 数据与 manifest：

- `backend/tests/fixtures/event_eval_1_0.jsonl`
- `backend/tests/fixtures/event_eval_1_0_manifest.json`

每个 pair 使用 `same_event`、`event_update`、`commentary`、`duplicate`、`unrelated` 之一作为 `relation`。左右条目都要包含 `id`、`title`、`language`、`source_role`、`gold_event_id`。正式集还必须满足：

- 至少 30 个跨小时/跨天 `sequence_id`；
- 至少 20 个 `high_similarity_negative`；
- 至少 20 个 `cross_language_positive`；
- 难例由两名标注人处理并包含 `adjudication.verdict`；
- 带独立 `test` split；正式指标只在该 split 上计算。

两个 manifest 都必须声明 `dataset_tier=formal_eval_1_0`、`release_scope=algorithm_and_ui_release_gate`、dataset SHA-256、commit、配置版本、抽样区间、脱敏、标注、质量检查、split、限制与标注人。

## 2. 正式评测

```bash
cd backend
uv run python scripts/run_formal_eval.py \
  --baseline artifacts/production_formal_eval_report.json \
  --output artifacts/formal_eval_report.json
```

阈值集中在 `backend/scripts/formal_eval_config.json`，其 hash 会进入报告。输出包括：

- Core precision/recall/F1/confusion matrix；
- NDCG@K、MRR、Recall@K；
- Brier、ECE 与 reliability diagram 数据点；
- F1/NDCG bootstrap 置信区间；
- 按来源类型、语言、付费墙、正文长度和 case type 分层；
- Event pairwise、B-cubed、Wrong/Missing Merge、跨小时连续性；
- 按关系、case type、语言对、来源角色和 split 分层；
- 与生产基线的数值 diff 及逐样本失败清单。

Event ID Churn 必须来自真实 v0/v1 stable assignment Shadow diff；离线二元 pair 聚类不会伪造该指标。

## 3. Shadow

生产并行路径按天导出结构化 JSONL snapshot，然后生成脱敏报告：

```bash
cd backend
uv run python scripts/run_quality_shadow.py ~/.pim/data/m2-shadow/snapshots.jsonl \
  --output ~/.pim/data/m2-shadow/reports/latest.json \
  --salt 2026-07-m2 \
  --retention-days 30 \
  --prune-directory ~/.pim/data/m2-shadow/reports
```

Snapshot 可含 `score_diffs`、`event_diffs`、`today_diffs`。报告固定声明 `shadow_only=true`、`production_affected=false`，删除正文、标题、URL、凭据和自由文本，并对 ID 做 pseudonymization。高风险 diff 必须人工复核。最低 Shadow 7 天，推荐 14 天。

## 4. 反馈裁决

Event UI/API 只创建 observation：

- `event_wrong_merge`
- `event_missing_merge`
- `event_wrong_title`
- `event_wrong_fact`
- `event_wrong_source_role`

队列：`GET /api/events/quality-feedback/queue`

裁决：`POST /api/events/quality-feedback/{feedback_id}/adjudicate`

只有 `confirmed` 的显式质量反馈会标为 `gold_candidate`；确认的 wrong merge 同时成为 `hard_negative`。`open`、`star`、`hide` 等自然阅读行为不会进入质量队列，也不会修改通用评分。

## 5. Release artifact

```bash
cd backend
uv run python scripts/generate_release_eval_artifact.py \
  --formal-report artifacts/formal_eval_report.json \
  --shadow-report ~/.pim/data/m2-shadow/reports/latest.json \
  --performance artifacts/performance_baseline.json \
  --approver data-owner \
  --approver product-owner \
  --output artifacts/release_eval_artifact.json \
  --enforce
```

Artifact 记录 commit、config/lock/dataset hash、Core/Event/Ranking/Calibration、生产 diff、Shadow、性能、已知失败样本、审批人与 Go/No-Go。任一真实数据、指标、Shadow、性能或审批门禁缺失都会得到 `NO_GO`；`--enforce` 会返回非零退出码。
