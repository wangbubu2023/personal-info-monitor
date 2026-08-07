# PIM Next Stage Upgrade 交付文档

交付日期：2026-08-07
依据文档：`PIM_Next_Stage_Upgrade_PRD_2026-07-22.md`、`SITE_RULES_PRD.md`、`M4_付费源Brief与Topic闭环.md`、`M5A_身份安全与双数据库Profile.md`、`M5B_Source连接器与Push集成.md`、`M6_工程治理SLO与发布门禁.md`

## 1. 交付结论

本次已完成 M4、M5A/M5B、M6 及 Site Rules 的可在本地闭环验证的代码、数据库迁移、API、前端页面、测试和治理脚本。当前仓库的后端全量自动化测试、前端单测/E2E、迁移回滚、静态门禁和认证助手单元测试均通过。

正式发布状态为 **NO_GO**。这不是代码测试失败，而是发布门禁按设计 fail-closed，仍缺少真实数据、人工标注、真实付费源运行周期和安全评审等外部证据；未使用伪造数据或伪造签字绕过门禁。阻塞项见第 5 节。

## 2. 已落地范围

| 范围 | 已完成内容 | 状态 |
| --- | --- | --- |
| M0–M3 基线 | 保留既有 FetchJob、Outbox、Event v1、质量反馈、AI 策略迁移和持久化契约；新增代码通过全量回归，离线评测回归门禁通过 | ✅ |
| M4 产品闭环 | Brief 版本化、不可变快照、supersedes lineage、周/月生成与查询；Topic 列表、编辑、归档、摘要；Local Capture 重放保护、审计关联、状态查询；付费源健康快照和 Daily Canary | ✅ 本地闭环 |
| M5A 身份安全 | User/Device/ServicePrincipal/IdentitySession/AuditActor 模型；短期 access token、refresh rotation、token family reuse 撤销、设备撤销和审计；CSRF double-submit、Origin 检查、CSP/安全响应头 | ✅ 本地闭环 |
| M5A 客户端 | Auth Assistant 的 WebView cookie/host 规范化契约、TypeScript 构建、Rust 测试和无 bundle Tauri 构建 | 🟡 尚未完成生产 Keychain/Stronghold 接入 |
| M5B Source | Source fetch/discovery/session/policy 状态拆分表；source metadata v1 规范化、敏感字段隔离/拒收和大小限制；state 查询及 backfill API | ✅ |
| M5B Connector | Connector manifest、capabilities、probe/fetch/hydrate/normalize/health 合同、默认拒绝权限、RSS 参考实现、注册表和 conformance 校验 | ✅ SDK/合同；第三方生产连接器待补 |
| M5B Push | WebSub callback 验证、租约/密钥哈希、HMAC、XML 解析、重放保护和 FetchJob；Webhook 目标校验、事件过滤、HMAC timestamp/nonce、Outbox 投递、重试和 DLQ 状态 | 🟡 WebSub lease renewal、fallback polling、真实适配器和生产端到端证据待补 |
| M6 工程治理 | architecture manifest 与边界校验、SLOLedger、BLE001/死代码/导入边界门禁、release-gate 报告、CI 接入、OpenAPI 类型生成 | ✅ 已落地的治理代码 |
| Site Rules | SiteRule 合同、严格校验、host/path matcher、优先级解析、编译限制、注册表、resolver、诊断计数器和 fail-closed；CollectorStage 已接入规则解析并保留通用 fallback | 🟡 仅合成 `example.com` 安全 fixture；NYT/黄金数据/生产 Shadow 未完成 |

主要新增数据库迁移为：

- `20260807_0041_m4_product_surface.py`
- `20260807_0042_local_capture_canary.py`
- `20260807_0043_source_state_split.py`
- `20260807_0044_integrations.py`
- `20260807_0045_identity.py`

当前 Alembic head 为 `20260807_0045`。

## 3. 验证结果

| 验证项 | 结果 |
| --- | --- |
| 后端全量 | `PYTHONPATH=. .venv/bin/pytest -q --no-cov --tb=short`：**1837 passed, 7 skipped, 13 warnings**，88.38 秒 |
| 后端编译/Ruff | `compileall` 通过；`ruff check app` 通过 |
| 后端治理门禁 | BLE001：`188 <= 188`；Vulture：`562 <= 568`；domain imports：441 个文件 clean；architecture manifest：4 entrypoints/4 contracts 通过 |
| 离线评测回归 | 通过；precision@20=0.5、source coverage@20=1.0、duplicate rate=0.25 |
| 数据库 | 空库升级到 head、降级到 `20260730_0040`、再升级到 head 全部成功 |
| 前端 | ESLint、TypeScript/Vite build 通过；Vitest **29 files / 131 tests passed**；OpenAPI 类型生成幂等 |
| 前端 E2E | Playwright **5 passed** |
| 前端依赖审计 | 通过；现有 GHSA-qwww-vcr4-c8h2 临时例外有效期至 2026-09-01，原因是本项目使用 declarative BrowserRouter、无 RSC server/action runtime |
| Auth Assistant | pinned-deps 检查和前端 build 通过；`cargo test --locked`：**3 passed**；Tauri `--no-bundle` 构建已通过 |
| 生产发布门禁 | **NO_GO**；详见第 5 节，脚本没有放宽失败条件 |

已验证的核心入口：

```text
backend/tests/test_m5_m6_contracts.py
backend/tests/test_alembic_fresh_upgrade.py
backend/scripts/validate_architecture_manifest.py
backend/scripts/check_offline_eval_regression.py
backend/scripts/run_release_gate.py
frontend/src/pages/TopicsPage.tsx
frontend/src/pages/BriefsPage.tsx
```

## 4. 交付物位置

- Site Rules：`backend/app/domains/fetch/site_rules/`、`backend/app/interfaces/http/site_rules.py`
- Topic/Brief：`backend/app/domains/events/topic_service.py`、`backend/app/domains/enrich/brief_service.py`、`frontend/src/pages/TopicsPage.tsx`、`frontend/src/pages/BriefsPage.tsx`
- Local Capture/Canary：`backend/app/domains/fetch/local_capture.py`、`backend/app/domains/fetch/daily_canary.py`
- Source/Connector/Push：`backend/app/domains/sources/`、`backend/app/domains/fetch/connectors/`、`backend/app/domains/fetch/websub.py`、`backend/app/domains/notifications/webhooks.py`
- Identity/CSRF：`backend/app/domains/identity/`、`backend/app/platform/auth/csrf.py`、`backend/app/interfaces/http/identity.py`
- M6 治理：`backend/docs/architecture_manifest.json`、`backend/scripts/validate_architecture_manifest.py`、`backend/scripts/run_release_gate.py`、`.github/workflows/ci.yml`
- 测试：`backend/tests/test_m5_m6_contracts.py`

## 5. 未完成项与发布阻塞项

以下项目明确保留为未完成，不应标记为“已验收”：

| 阻塞项 | 需要的完成条件 | 责任/依赖 |
| --- | --- | --- |
| Event Bootstrap / 人工标注 | 安装 PRD 要求的 Event 数据集，完成双人标注、冲突仲裁和可复现 Event Eval；当前 `check_bootstrap_eval.py` 报 `event_bootstrap_v0_1.jsonl` 不存在 | 产品/数据标注/评测负责人 |
| Shadow Eval | 提供 `tests/fixtures/shadow_eval_1_0.jsonl` 及版本哈希，完成真实 Shadow 对比 | 产品/评测负责人 |
| Site Rules NYT | NYT 真实 fixture、listing/RSS discovery、gold labels、Web Clean 结果、版权/隐私/安全审查、LKG 与 production Shadow/rollback 证据 | 采集/评测/法务与安全 |
| 真实付费源运行证据 | 配置已授权付费源，完成 Extension/Tauri 可见 WebView Local Capture、恢复演练，连续 7–14 天 Daily Canary/Shadow，给出 SLO、回滚和告警证据 | 运维/账号授权/人工操作 |
| Security Review | 添加经过批准的 `docs/SECURITY_REVIEW_APPROVAL.md`；当前文件不存在 | 安全评审人 |
| Server 身份与部署 | OIDC/passkey provider、完整 Web BFF E2E、PostgreSQL profile/capacity、备份恢复/回滚、TLS/KMS 和生产配置验证 | 后端/平台/安全 |
| Tauri 密钥保护 | 将客户端敏感凭据接入系统 Keychain/Stronghold，并完成 macOS 打包后的安全验证 | 客户端/平台 |
| Push 生产能力 | WebSub lease renewal/fallback polling、Slack/Teams/Telegram/Notion 等实际 adapter、真实 provider 签名和投递日志验证 | 集成/平台 |
| M6 全量供应链门禁 | GitHub Actions SHA pin、pyright/mypy、Bandit、Semgrep、CodeQL、secret scan、cargo audit/SBOM 等按 PRD 接入并留存结果 | 工程治理/平台 |
| 文件行数门禁 | 当前仓库仍有既有超限文件：`backend/app/domains/fetch/collectors/website.py` 1640>1466、`pim` 1703>1687、`frontend/src/components/Settings/CredentialsTab.tsx` 987>975；本次未修改这些文件 | 工程治理/后续拆分 |

发布门禁脚本的当前结果：

```json
{
  "status": "NO_GO",
  "missing": [
    "shadow_eval_dataset",
    "security_review_approval",
    "real paid-source 7-14d Shadow/Canary evidence"
  ]
}
```

## 6. 建议的后续放行顺序

1. 产品/数据负责人先补齐 Event、Shadow 和 Site Rules gold 数据，并保存数据版本、哈希及人工标注记录。
2. 安全评审完成身份、CSRF/CSP、凭据存储、Webhook/WebSub、版权/隐私和供应链审查，提交签字文件。
3. 运维接入授权付费源，完成 Local Capture 恢复演练及 7–14 天 Canary/Shadow，记录 SLO、告警、DLQ 和回滚。
4. 完成 PostgreSQL、OIDC/passkey、Keychain/Stronghold 和第三方 Push adapter 的生产验证。
5. 修复文件行数与剩余供应链静态门禁后，重新执行 `backend/scripts/run_release_gate.py`；只有结果变为 `GO` 才进入发布。

本交付文档不把上述外部依赖折算为代码完成度，也不建议在缺少证据时强行发布。
