# ADR-005: 后端六模块领域边界

## 状态

已接受（2026-05 修订：fetch 扩权、score 独立、summarize 流水线阶段）

## 背景

PIM 后端在 Phase 0–7 完成五模块拆分后，实践中发现：(1) 正文二跳与验收逻辑落在 `ingest` 但与「抓取交付完整原始内容」语义不符；(2) 评分规则持续演进，与清洗入库耦合；(3) LLM 摘要应在打分前产生 canonical summary，但不宜打破 ingest 无 LLM 约束。

## 决策

1. **领域层**划分为六个包，流水线单向依赖：
   `sources` → `fetch` → `ingest` → `score`；`ingest` → `enrich`（summarize 子阶段）；`atoms` 可选 sidecar。
2. **fetch** 负责 collector、**正文二跳**（`fetch/article_body`）、**验收**（`fetch/acceptance`），交付 `fetch_acceptance=accepted` 的完整原始内容（X 短帖除外）。
3. **ingest** 仅做确定性预处理（清洗、去重、入库、FTS、关键词）；**禁止 LLM**。
4. **score** 独立为 `domains/score`；打分只读**原文** `title` / `summary`（listing 翻译纯 UI）。
5. **summarize** 为第七个**流水线阶段**，由 `enrich/content/summarize` 实现，在 `ingest/finish` 中于 score 之前同步调用；受 `ENRICH_AUTO_ON_INGEST` + `ENRICH_SUMMARY_ENABLED` 控制。
6. 共享 fulltext 常量置于 `domains/contracts/content_quality.py`，供 fetch 验收与 ingest 质量元数据共用。
7. **导入约束**见 `check_domain_imports.py`（含 `fetch` 不得 import 下游、`score` 不得 import enrich）。

## 参考

- [MODULE_BOUNDARIES.md](./MODULE_BOUNDARIES.md)
- [SCORING_MODEL.md](./SCORING_MODEL.md)
