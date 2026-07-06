# Reviews & 历史计划归档

本目录汇总 PIM 历次代码审计、重构计划、阶段设计文档。活跃的设计与规范在
顶级 `docs/` 中维护，本目录只用于可追溯性和知识保留。

## 当前审阅需求

- `2026-07-02-pim-expert-review-brief.md` — 面向外部专家团队的综合代码审阅需求文档，重点关注抓取架构、各类内容源策略、网站最新信息发现能力、事件聚类/评分算法与代码 bug。
- `2026-07-02-fetch-field-test.md` — 20 个真实启用信源的 dry-run 实测表输出位置。生成命令：
  `cd backend && ./.venv/bin/python scripts/run_fetch_field_test.py --limit 20 --sample-limit 5 --output ../docs/reviews/2026-07-02-fetch-field-test.md --json-output ../docs/reviews/2026-07-02-fetch-field-test.json`。
  无 X cookie 的本地环境可先跑非 X 子集：
  `cd backend && ./.venv/bin/python scripts/run_fetch_field_test.py --exclude-type x --limit 20 --sample-limit 5 --output ../docs/reviews/website-rss-field-test.md`。
- `2026-07-04-fetch-field-followup.md` — 对 20 源实测中 36kr / Engadget `would-store=0` 现象的复核；当前结论是正常重复过滤，不是抓取失败。

## 归档（`archive/`）

### 已完成的重构 / 设计计划

- `MODULE_REFACTOR_PLAN.md` — 后端五领域模块化重构方案（Phase 0–7 全部
  ✅ 已合并）。整篇文档现在是完整的实施记录 + 历史路径映射。**当前
  事实**改看 `docs/ARCHITECTURE.md`、`docs/MODULE_BOUNDARIES.md`
  与 `docs/PROJECT_STRUCTURE.md`。
- `CLI_SPEC.md` — `./pim` 与 `pimctl` 的设计规划（v0.3，2026-04-12 同步）。
  Phase 1 MVP + Phase 2 扩展已落地；Phase 3 MCP 兼容尚未实施。**用户向
  命令参考**改看 `docs/PIMCTL_REFERENCE.md`；MCP 推进时再回查本文档。
- `audit-fix-plan.md` — 2026-04 第三版代码审计后的修复实施计划
  （16 项问题，已落地）。
- `AI_DECOUPLING_REFACTOR_PLAN.md` — AI 解耦第一版计划（已被 Phase 4
  enrich 重构覆盖）。
- `pim_aihot_upgrade_plan_2026-05-07.md` — 借鉴 AIHOT 的 3 小时报 / atoms /
  分维度评分升级计划。其中 atoms 层与 3 小时报已在 Phase 6 / Phase 4
  step 6 落地；其余事件聚类 / 维度评分若需推进，请参考蓝图最新版本。

### 历史代码审计

- `audit-2026-05-02/` — 第四版代码审计 11 件套（架构 / 安全 / 流水线 / AI /
  API / DB / 调度 / 测试 / 前端 / CLI / 依赖与规范），含原始 plan
  `_audit-plan.md`。审计结论中的 P0/P1 都已通过 2026-03–05 的模块化
  重构 Phase 0–7 落地。

### Superpowers 流并行实施计划

- `superpowers-plans/` — 原 `docs/superpowers/plans/`，按 Stream 划分的并行实施计划。
- `superpowers-specs/` — 原 `docs/superpowers/specs/`，Phase 2/3 设计文档。

## 补充参考（活文档）

- 当前架构：`docs/ARCHITECTURE.md`
- 模块边界：`docs/MODULE_BOUNDARIES.md`
- 全量目录说明：`docs/PROJECT_STRUCTURE.md`
- API / `rate()` 指南：`docs/API_GUIDE.md`
- 部署：`docs/VPS_DEPLOY.md`、`docs/LOCAL_RUN.md`
- v1.4 发布/验收交接：`docs/V1_4_RELEASE_HANDOFF.md`
- CLI 命令参考：`docs/PIMCTL_REFERENCE.md`
