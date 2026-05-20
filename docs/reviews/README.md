# Reviews & 历史计划归档

本目录汇总 PIM 历次代码审计、重构计划、阶段设计文档。活跃的设计与规范在
顶级 `docs/` 中维护，本目录只用于可追溯性和知识保留。

## 归档（`archive/`）

- `audit-2026-05-02/` — 第四版代码审计 11 件套（架构 / 安全 / 流水线 / AI /
  API / DB / 调度 / 测试 / 前端 / CLI / 依赖与规范），含原始 plan
  `_audit-plan.md`。审计结论中的 P0/P1 都已通过 2026-03–05 的模块化
  重构 Phase 0–7 落地。最新事实以 `docs/ARCHITECTURE.md`、
  `docs/MODULE_BOUNDARIES.md`、各 ADR 与 `docs/MODULE_REFACTOR_PLAN.md`
  为准。
- `audit-fix-plan.md` — 2026-04 第三版代码审计后的修复实施计划（16 项问题，已落地）。
- `AI_DECOUPLING_REFACTOR_PLAN.md` — AI 解耦第一版计划。
- `pim_aihot_upgrade_plan_2026-05-07.md` — 借鉴 AIHOT 的 3 小时报 / atoms /
  分维度评分升级计划。其中 atoms 层与 3 小时报已在 Phase 6/Phase 4 step 6
  落地；其余事件聚类 / 维度评分若需推进，请参考蓝图最新版本。
- `superpowers-plans/` — 原 `docs/superpowers/plans/`，按 Stream 划分的并行实施计划。
- `superpowers-specs/` — 原 `docs/superpowers/specs/`，Phase 2/3 设计文档。

## 补充参考

- 当前架构：`docs/ARCHITECTURE.md`
- API / `rate()` 指南：`docs/API_GUIDE.md`
- 部署：`docs/VPS_DEPLOY.md`、`docs/LOCAL_RUN.md`
- CLI：`docs/CLI_SPEC.md`、`docs/PIMCTL_REFERENCE.md`