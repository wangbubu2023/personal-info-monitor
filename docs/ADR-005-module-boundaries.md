# ADR-005: 后端五模块领域边界

## 状态

已接受（Phase 0–7 全部落地；post-Phase-7 仓库审计完成）

## 背景

PIM 后端在 `collectors`、`pipeline`、`processors`、`tasks`、`api/sources/_helpers` 等目录间存在职责重叠与反向依赖。计划引入「新闻原子」结构化能力，需要稳定的扩展点。团队希望按模块单独优化、测试与排障。

## 决策

1. **领域层**划分为五个包，单向依赖：`sources` → `fetch` → `ingest` → `atoms`；`ingest` → `enrich`；`atoms` 对 `enrich` 为**可选上游**（L0/L1/L2 消费级别，见 [MODULE_REFACTOR_PLAN.md](./MODULE_REFACTOR_PLAN.md)）。
2. **交付层**（`interfaces/http`、`cli/pimctl`、`frontend`、`./pim`）不承载业务规则，不列为第六个领域模块。
3. **平台层**（`platform/*`）承载认证、配置、数据库、任务队列、指标、浏览器池、SSRF/加密等横切能力。
4. 抓取主路径**禁止 LLM**；摘要/翻译/简报仅在 `enrich`；结构化原子在 `atoms`。
5. 删除未接入流水线的 `pipeline/ai_stage.py`；调度 due 逻辑收口至 `sources/scheduling`。
6. **导入约束由静态检查器强制**：`backend/scripts/check_domain_imports.py` 在 CI 中按 `--phase=7` 校验全部依赖方向，post-Phase-7 仓库审计追加规则禁止重新引入已删除的 shim（`app.collectors.podcast / website_helpers / x_twitter_formatters`、`app.data.source_types`、`app.exporters`、`app.utils.{ssrf,tracing}`、`app.tasks.{email_tasks,fetch_orchestrator,hourly_digest_tasks}`、`app.services.{runtime_lock_service,system_settings,hourly_digest,reader}`）。

## 原因

- 与 ADR-001 本地单体一致：包边界替代微服务。
- 便于分 PR 迁移、按 domain 过滤日志与指标。
- atoms 可选上游避免 enrich 被结构化流水线阻塞。

## 后果

### 优点

- 新人可按模块阅读代码与文档。
- 单模块测试与发布风险隔离。
- 为 atoms 预留清晰落点。
- 顶层文档（README、ARCHITECTURE、MODULE_BOUNDARIES、`backend/README.md`）已在 Phase 7 后集中更新；audit/ 目录历史快照归档至 `docs/reviews/archive/audit-2026-05-02/`。

### 代价

- 部分高 fan-out 的 shim 仍保留以维持 `patch()` target（如 `app.config`、`app.database`、`app.auth`、`app.background`、`app.collectors.{base,rss,youtube,x_twitter,...}`、`app.utils.{logger,metrics,encryption}`），未来如要删除需要先在测试中改 patch target。
- `app.api → app.interfaces.http` 通过 `sys.modules` 别名共存；删除别名需要先在 `app/main.py` 与所有测试中改 import 路径。

## 参考

- [MODULE_REFACTOR_PLAN.md](./MODULE_REFACTOR_PLAN.md)
- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [ADR-001-local-monolith.md](./ADR-001-local-monolith.md)
