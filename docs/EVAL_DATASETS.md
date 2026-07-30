# PIM 人工评测集清单

更新时间：2026-07-30

## 已建立

### Core Bootstrap v0.1

- 数据：`backend/tests/fixtures/core_bootstrap_v0_1.jsonl`
- Manifest：`backend/tests/fixtures/core_bootstrap_v0_1_manifest.json`
- 规模：100 条、23 个来源
- 标签：`must_see=4`、`ok=35`、`noise=61`
- 用途：M0/M1 基础设施 fail-closed 门禁、评分链路冒烟和回归检查
- 状态：数据与 manifest 契约通过；与 Formal Core 样本完全隔离

### Core Eval 1.0

- 数据：`backend/tests/fixtures/core_eval_1_0.jsonl`
- Manifest：`backend/tests/fixtures/core_eval_1_0_manifest.json`
- 最新报告：`~/.pim/data/eval/gold/formal_eval_report.json`
- 规模：400 条
- 用途：Core relevance 分类、排序、分数阈值和校准
- 状态：Formal Core 数据契约通过，运行时重新计算当前评分，不读取历史预测
- 首次 `pim-score-v2.3` 基线：
  - Precision：0.430233
  - Recall：0.725490
  - F1：0.540146
  - NDCG@20：0.573031
  - Brier：0.290980
  - ECE：0.262544

### Core Quality v0.1

- 数据：`~/.pim/data/eval/gold/core_quality_v0_1.jsonl`
- Manifest：`~/.pim/data/eval/gold/core_quality_v0_1_manifest.json`
- 规模：416 个唯一内容样本
- 可用人工标签：
  - relevance：413 条
  - quality：411 条
  - fact density：175 条
  - lane fit：246 条
- 用途：内容相关性、正文/摘要质量、事实密度和旧 lane 适配分析
- Review queue：`~/.pim/data/eval/gold/review_queues/core_quality_adjudication_v0_1.jsonl`
  - 5 个重复样本需要裁决
  - relevance 冲突 3 个，quality 冲突 5 个

### Lane Eval v0.1 Seed

- 数据：`~/.pim/data/eval/gold/lane_eval_v0_1.jsonl`
- Manifest：`~/.pim/data/eval/gold/lane_eval_v0_1_manifest.json`
- 规模：163 条
- 已覆盖：公司新闻、产品新闻、市场交易、监管政策、宏观金融、地缘外交、创投融资、公共人物、其它
- 用途：13 类 lane 分类器的首批回归集
- Review queue：`~/.pim/data/eval/gold/review_queues/lane_eval_v0_1_needs_review.jsonl`
  - 83 条需直接按新 13 类补标

### Event Card Correctness v0.1

- 数据：`~/.pim/data/eval/gold/event_card_correctness_v0_1.jsonl`
- Manifest：`~/.pim/data/eval/gold/event_card_correctness_v0_1_manifest.json`
- 规模：42 条明确、无冲突的人审 Event
- 标签：`correct=4`、`partial=11`、`incorrect=27`
- 用途：判断 Event 卡片本身是否成立
- Review queue：`~/.pim/data/eval/gold/review_queues/event_card_correctness_v0_1_needs_review.jsonl`
  - unclear 31 条、冲突 2 条、未标 1 条
- 限制：不用于事件 pair、member assignment、Wrong/Missing Merge 或 B-cubed

## 仍需补齐

### Lane Eval 完整覆盖

- 当前缺少 `domestic_politics`、`public_safety`、`macro_economy`、`industry_news`
- 83 条旧 taxonomy 样本需要直接按新 13 类重标
- 每类还需要补充正常样本、边界样本和高相似负例，避免 seed set 只覆盖旧分类错误

### Event Bootstrap Pair Eval

- 目标：至少 15 个真实事件簇、50 个同/不同事件 pair
- 当前导出 Event 只有 0 或 1 个 member，无法组成 pair gold
- 必须重新抽取两个内容构成的 A/B 标注任务
- 当前门禁报告：`~/.pim/data/eval/gold/bootstrap_gate_report.json`

### Event Eval 1.0

- 目标：至少 50 个 gold 簇、200 个 pair
- 需要覆盖跨语言正例、高相似负例、同公司不同事件、跨小时/跨日序列和五类关系
- 难例需要双人标注与 adjudication

### Today v0/v1 Diff Eval

- 当前只有 3 条导出记录且均未标
- 需连续采集至少 7 天，推荐 14 天，再标记 acceptance 与 regression

### Event Title Rewrite Eval

- 当前没有人工 title rewrite 标签
- 需覆盖问句、评论、传闻、否认、连续版本发布和主体/动作缺失等高风险模态

## 生成与验证

```bash
cd backend

# 查看将生成什么
uv run python scripts/build_eval_assets_from_annotations.py

# 从不可变源资产重新生成
uv run python scripts/build_eval_assets_from_annotations.py --apply

# Core Bootstrap 数据契约
uv run python scripts/check_core_eval_dataset.py \
  --dataset tests/fixtures/core_bootstrap_v0_1.jsonl \
  --manifest tests/fixtures/core_bootstrap_v0_1_manifest.json \
  --min-records 50 \
  --min-sources 3

# Core/Event 综合门禁；Event pair 未补齐前整体应保持 fail-closed
uv run python scripts/check_bootstrap_eval.py
uv run python scripts/run_formal_eval.py
```

源资产：

- `~/.pim/data/eval/eval_set_v1_4_2026-07-06.jsonl`
- `~/Downloads/eval_export_20260724_074010.zip`
- `~/Desktop/labels/`

## 持续标注入口

`dev` 的 Development Profile 采用“消费即标注”，不要求日常进入独立工作台。使用说明见
`docs/DEVELOPMENT_PROFILE.md`。明确的人审标签与必要裁决可通过
`backend/scripts/export_annotation_eval.py` 导出为带 manifest 的版本化评测资产。

当前持续积累的增量信号包括：内容价值（正式的“重要/不重要”）、内容质量、格式质量、
内容 Tag、Event 误合/漏合，以及 Atom 编辑/核验。未进行价值操作的内容自然视为一般，
但不会写入显式 `ok` 标签。

这些源文件不被生成脚本修改。每个生成集的 manifest 都记录源文件 hash、数据集 hash、当前 Git commit、评分版本、标注人和已知限制。
