# Personal Info Monitor 主升级 PRD Milestone 0–4 独立工程审计

- 审计角色：外部高级工程师
- 审计日期：2026-07-29
- 审计对象：附件完整受管源码快照（声称对应 `main @ b17e71ee0715cace333f6e2da3adfb1b29f9a5ae`）
- 附件：`PIM_M0-M4_WebClean_Audit_b17e71e.zip`
- 附件实测大小：2,317,296 bytes
- 附件实测 SHA-256：`fb6f09456496134e7217cb1b8352acc5e394b2615f75160cfc26ae07c1484fe2`
- ZIP 完整性：`unzip -t` 通过，876 个文件
- 重要限制：附件不含 `.git` 元数据，因此无法独立证明其 Git commit 确为 `b17e71e...`，也无法核验“本地领先 origin/main 3 个提交”。本报告及补丁以附件中未经修改的文件内容为唯一基线。

## 1. 执行摘要

### 1.1 总体结论

**结论：M0–M4 不能整体标绿。** 当前源码包含大量真实工程实现，尤其是 M0/M1/M1A/M2/M3 的底座、迁移和 fail-closed 框架；但 30.3 台账把若干“代码外壳或单元路径存在”写成“工程已完成”，并引用了附件中无法复核的测试计数、真实数据库迁移、备份、生产基准和长稳数据。M4 的“9/9 工程批次完成”尤其不成立。

审计在附件基线中发现并修复了以下仓库内可确定缺陷：

1. **Local Capture 安全边界实际为 fail-open**：公开硬编码 HMAC salt、同秒确定性 token、未来时间 token 可被 `abs()` 接受、未配置 allowlist 时默认放行、allowlist 由客户端提交且使用子串匹配、未校验设备有效性、无数据库级防重放。
2. **真实 Auth Assistant ZIP 导入路由绕过安全解析器**：上传整体无界读取，随后直接按 manifest 路径 `archive.read()`；原 `auth_zip.py` 的限制只被独立测试调用，并未保护实际导入路径。
3. **Paid-source Matrix 可把 HTTP 500 + 长正文记为成功**，并把单次结果伪装成“7 天成功率”；失败还会清空历史最近成功时间。
4. **Brief 所谓“不可变快照”会原地覆盖已发布记录**；lineage 接受不存在的 Snapshot ID；未知 modality 被静默降为 `reported`；Brief 与 violation audit 分两次提交；任意 Brief 可无理由解除违规。
5. **Topic 来源覆盖把 `canonical_content_id` 当作来源 ID**，未验证关联的 Event 是否存在，并发关联可撞唯一键。
6. **M1 后处理幂等键丢弃内容 fingerprint**，同 pipeline version 的实质更新可能被旧的 succeeded job 抑制。
7. **M4 curated/full 仅存在测试辅助/展示函数，真实 Event detail API 默认仍返回全量 timeline**；前端没有显式 full 查询开关；v1 Event Markdown 导出仍只查 legacy membership。
8. 修补 curated/full 时进一步发现并消除一个 **Python 字典重复 `extra` 键覆盖** 风险，并用 API 测试要求 `view_mode/report_count` 与原有诊断字段共存。
9. **顶层 `./pim` 的最小 `.env` 回退重新写入已弃用的 AI 产品开关**，会绕过 `system_settings` 唯一产品控制面；已移除该回退并补 CLI 回归测试。
10. 架构文档一处写成 CLI 与后端“共享 SQLite”，与实际强制 HTTP-only 边界冲突，已纠正。

### 1.2 各里程碑判定

| 里程碑 | 审计判定 | 说明 |
|---|---|---|
| M0 | **工程大部落地；真实 Bootstrap 外部阻塞；含 1 个仓库内幂等缺陷已修复** | StorageResult、missing content、durable fetch、Web bootstrap 均有实现；真实 Core/Event Bootstrap 文件缺失，门禁正确 NO-GO。选定 M0/M1 回归包含在 87 个 pytest 通过项中，但真实 kill/queue/DB/provider 故障演练仍未执行。 |
| M1 | **工程机制大部落地；生产 SLO/长稳未验收** | durable job、lease/CAS、shutdown、ledger、outbox、lineage、Write Queue、ADR 均有代码；accepted-job no-loss、真实 SIGKILL/provider 故障和 7 天窗口不能从仓库证明。 |
| M1A | **工程机制大部落地；1 个控制面回退缺陷已修复；真实 provider 验收外部阻塞** | 800 字、并发 2、缓存、configured/ready、budget、system_settings、hard disable、Shadow 权重 0 均有代码；补丁移除 `./pim` 在缺少 `.env.example` 时生成旧 `AI_PROCESSING_ENABLED/ENRICH_*` 开关的行为；真实 401/429/不可达与计费未验证。 |
| M2 | **框架落地；正式质量闭环阻塞，当前必须 NO-GO** | 正式 runner、指标、Shadow、adjudication、release artifact 均存在；正式数据集、manifest、人工标注、生产 Shadow、性能和审批缺失。 |
| M3A | **工程内核大部落地；正式质量门禁未满足** | stable ID、Signature、召回/分类、Snapshot、alias/operation、Today v1 preview 等存在；真实 Wrong/Missing Merge、Recall/P95、连续 ID churn 不存在。 |
| M3B | **工程机制部分落地；read gate 正确关闭；生产灰度阻塞** | rebalance、merge/split/revert、diff audit、双跑和双门控存在；0 天生产 Shadow，普通 UI 不能切 v1。P3 正确未启用。 |
| M4 | **台账误报；补丁后仍仅“部分实现/阻塞”** | M4-05 可认为仓库内工程完成；M4-01/08/09 经补丁后具备更可信实现；M4-02/03/04/06/07 仍缺真实演练、浏览器 worker/入库、scheduler+真实 fetch、一级 UI、生成/读取 UI 等关键闭环。 |

### 1.3 发布结论

当前应保持：

- **总发布：NO-GO**；
- **Event v1 普通 UI read switch：关闭**；
- **M0/M2 正式评测：缺真实数据时 fail-closed**；
- **主观评分：Shadow、权重 0**；
- **M4：不得写成 9/9 工程完成，更不得因补丁通过局部测试而宣称生产验收完成。**

## 2. 审计范围与方法

完整阅读/检查范围包括：

- 根目录 `README.md`、主 PRD、架构/模块边界/持久化/Event 迁移文档；
- `backend/pyproject.toml`、`backend/uv.lock`、Alembic 配置和 0033–0038 迁移；
- `frontend/package.json`、`package-lock.json`、Vite/TypeScript/Vitest 配置；
- M0–M4 相关 domain、platform、HTTP API、models、scripts、tests、frontend API/types/UI；
- 主 PRD第 20 节里程碑、第 21 节发布门禁、第 28 节 DoD、第 30.3 节唯一进度表及矩阵。

审计方法：

1. 不以 30.3 台账为事实来源，逐项从源码反向追踪；
2. 对路由是否真正调用 domain、安全 helper 是否接入真实路径、前端是否真正有入口进行接线核查；
3. 对幂等、事务、CAS、唯一约束、重放、默认值、fail-open、迁移往返和 v0/v1 边界做负向审阅；
4. 对可在仓库内确定修复的问题生成最小 unified diff 和针对性测试；
5. 对真实样本、真实凭据、人工标注、生产流量、7 天长稳严格保留为外部阻塞。

## 3. Traceability Matrix

图例：

- **已实现**：代码路径真实接线，契约完整度可接受；
- **部分实现**：有核心代码，但缺必要接线、产品路径或关键语义；
- **未实现**：关键执行路径不存在；
- **外部阻塞**：必须由真实数据/凭据/流量/时间窗口/人工工作提供；
- **台账误报**：30.3 的状态或证据超过当前附件可证明范围。

“自动化验证”严格区分：仓库测试存在、此次正式测试实际执行、审计自建 harness。后者不替代项目正式 pytest。

### 3.1 M0：72 小时正确性红线

| 验收点 | 代码状态 | 本次自动化验证 | 真实验收 | 精确证据与结论 |
|---|---|---|---|---|
| M0-01 StorageResult 精确分类/计数守恒 | 已实现 | 选定回归 pytest 通过；编译/架构检查通过 | 生产数据分布仍需观察 | `backend/app/domains/ingest/storage.py:StorageResult`（当前 60–99），区分 saved/updated/unchanged/failed 并 `assert_conservation()`。 |
| M0-01 只有实质更新进入后处理 | 已实现 | 现有测试文件存在；未正式执行 | 生产重放仍需观察 | `storage.py:_SUBSTANTIVE_FIELDS/_SUBSTANTIVE_METADATA_KEYS`（112–128）、`StorageStage`。 |
| M0-01 后处理幂等包含 fingerprint | **基线错误，已修复** | 审计 harness 通过；新增 `test_m1_reliable_execution.py` 用例 | 无外部阻塞 | 基线 `postprocess_jobs.py:_pipeline_identity` 45–47 用 `split(...,2)` 只保留 pipeline version，丢掉 fingerprint；补丁后当前 41–55 保留 `finish:` 后完整 identity。 |
| M0-02 missing content typed failure，不记 success | 已实现 | 选定 M0 回归 pytest 通过；编译通过 | 真实库 dry-run 结果不可从附件证明 | `backend/app/domains/ingest/failures.py:IngestFailureCode.CONTENT_NOT_FOUND`（9–27）；审计脚本 `backend/scripts/audit_missing_postprocess_content.py` 存在。 |
| M0-03 durable FetchJob、queue full 留 pending、启动恢复 | 已实现 | 选定 M0/M1 回归 pytest 通过；真实故障进程测试未执行 | queue full/kill 的生产行为需真实演练 | `backend/app/platform/workers/fetch_jobs.py:create_fetch_job/acquire_fetch_job/heartbeat/mark_*`（65 起）；模型 `backend/app/models/fetch_job.py`。 |
| M0-04 Web 长期 Token 不进 HTML/query/storage | 已实现 | 选定认证回归 pytest 通过；代码审查 | 威胁模型/渗透不在附件 | `bootstrap_token.py` 1–7、41–63、97–109；`web_session.py` 31–85，单次 code、HttpOnly/Secure/SameSite cookie、CAS consume。 |
| M0-04 Tauri renderer 不读长期密钥 | 部分验证 | 未执行 Rust test | OS Keychain 实机需外部环境 | `frontend/src-tauri/src/lib.rs` 与 `frontend/src/services/api.ts`；本环境未安装/运行 Tauri 工具链测试。 |
| M0-05 Core Bootstrap 规范与无数据 fail-closed | 已实现 | **实际执行 RC=1，符合预期** | **外部阻塞** | `backend/scripts/check_bootstrap_eval.py:check_bootstrap_eval`（74 起）；目标 `backend/tests/fixtures/core_bootstrap_v0_1.jsonl` 缺失，输出 `core_records=0, ok=false`。 |
| M0-05 真实 Core v0.1-bootstrap | 未实现/外部阻塞 | 不可验证 | 需真实脱敏样本、人工标签、manifest | 附件不存在目标文件；现有 `eval_set.jsonl` 仅 4 行、`example.com` synthetic，且含预填 `article_score`，不能冒充验收。 |
| M0-06 Event Bootstrap 规范与无数据 fail-closed | 已实现 | **实际执行 RC=1，符合预期** | **外部阻塞** | `check_bootstrap_eval.py`；目标 `event_bootstrap_v0_1.jsonl` 缺失，输出 `event_pairs=0, ok=false`。 |
| M0-06 真实 Event v0.1-bootstrap | 未实现/外部阻塞 | 不可验证 | 需真实 ≥15 簇/50 pair 与人工复核 | 附件中无数据集/manifest。 |
| M0 退出：故障注入通过 | 部分实现/未验收 | 选定相关 pytest 通过；全量测试未完成，真实进程/外部故障注入未执行 | 生产 kill/queue/DB transient/provider failure 仍需演练 | 30.3 将历史测试结果写入台账，但当前快照无法复现。 |

### 3.2 M1：可靠执行底座

| 验收点 | 代码状态 | 本次自动化验证 | 真实验收 | 精确证据与结论 |
|---|---|---|---|---|
| M1-01 Durable Fetch/Postprocess Job | 已实现 | 编译、架构检查通过 | 生产重放观察外部阻塞 | `models/fetch_job.py`、`models/postprocess_job.py`；`fetch_jobs.py:create_fetch_job`、`postprocess_jobs.py:ensure_postprocess_jobs`。 |
| M1-01 统一业务幂等 | **部分实现→补丁修复明确缺陷** | targeted harness 通过 | 真实重复投递仍需观察 | fingerprint 丢失问题见 M0-01；补丁后 key 为 `content:stage:pipeline+fingerprint`。 |
| M1-02 Lease/heartbeat/CAS/stale owner | 已实现 | 选定 M1 回归 pytest 通过 | SIGKILL/网络分区长稳外部阻塞 | `fetch_jobs.py:acquire_fetch_job/heartbeat_fetch_job/_lease_filter/mark_*`；`postprocess_jobs.py` 对应函数。 |
| M1-03 Graceful shutdown/drain | 已实现 | 编译通过 | 正式进程管理器 SIGTERM/SIGKILL 外部阻塞 | `backend/app/platform/runtime/lifespan.py:build_lifespan`（210 起）、due-job 恢复（92–199）。 |
| M1-04 Scheduler ledger/misfire/catch-up | 已实现 | 架构检查通过 | 真实调度窗口外部阻塞 | `backend/app/platform/workers/scheduler_ledger.py:create_scheduler_run/execute_scheduled/record_misfires`。 |
| M1-05 Transactional Outbox/DLQ/idempotency | 已实现 | 编译通过 | provider 真实失败/重放外部阻塞 | `backend/app/platform/notifications/outbox.py:enqueue_email/_claim_event/dispatch_*`。 |
| M1-06 Lineage bounded trace | 已实现 | 编译通过 | 生产完整链路样本外部阻塞 | `backend/app/platform/persistence/lineage.py:add_lineage_edge/trace_lineage`。 |
| M1-07 SQLite Write Queue/Single Writer/backpressure | 已实现机制、待长稳 | 编译/架构通过；未复现台账 benchmark | **7 天 workload 外部阻塞** | `backend/app/platform/persistence/write_queue.py:SQLiteWriteCoordinator/AsyncWriteQueue`。附件无台账声称的 benchmark artifact。 |
| M1-08 Canonical Persistence Contract | 测试骨架存在 | SQLite/PostgreSQL 正式测试未执行 | PostgreSQL service 未提供 | `docs/CANONICAL_PERSISTENCE_CONTRACT.md`；`tests/test_persistence_contract.py`。30.3 声称 PostgreSQL `2 passed` 无可携证据。 |
| M1-09 Event Migration ADR/alias/operation/rollback | 已实现文档与 schema | 迁移 fresh/往返已执行 | 人工签字/真实 backfill 外部阻塞 | `docs/EVENT_V1_MIGRATION_ADR.md` 11–24、36、52–83；迁移 0034/0037。 |
| M1 退出：accepted job no-loss、delivery→fetch | 机制具备，未验收 | 无生产证据 | **外部阻塞** | 不能以测试文件存在或 synthetic benchmark 替代 SLO。 |

### 3.3 M1A：AI 模型治理 Phase 4/5

| 验收点 | 代码状态 | 本次自动化验证 | 真实验收 | 精确证据与结论 |
|---|---|---|---|---|
| 输入资格、最多 800 字、title-only/blocked 跳过 | 已实现 | 选定 M1A 回归 pytest 通过 | 真实内容分布需观察 | `backend/app/domains/score/score_subjective.py:SUBJECTIVE_MAX_BODY_CHARS=800`（22），输入组装与资格路径。 |
| input/model/prompt 幂等缓存 | 已实现 | 选定 M1A 回归 pytest 通过；真实 provider 重放未执行 | 云端计费实测外部阻塞 | 同文件 cache 查询/持久化（约 191–262）。 |
| LLM 并发 ≤2 | 已实现 | 选定 M1A 回归 pytest 通过；真实 provider 并发未执行 | provider 真实并发外部阻塞 | `score_subjective.py:_score_semaphore`（167–170）使用 `asyncio.Semaphore(2)`。 |
| Token/成本/预算 exhausted | 已实现机制 | 编译通过 | 真实账单/限流外部阻塞 | `backend/app/platform/llm/policy.py` 267–305、342–362，显式 `budget_exhausted`。 |
| configured/ready 分离 | 已实现 | 编译通过 | 真实 401/429/不可达外部阻塞 | `policy.py:AiCapabilityState`（37–40）、`_runtime_ready`、resolver。 |
| system_settings 唯一产品控制面 | **基线有回退缺陷，已修复** | 选定 M1A/CLI 回归 pytest 通过；架构检查通过 | 一次迁移真实库不可从附件证明 | `backend/app/platform/config/system_settings.py:get/update_system_settings_*`（494–624）及 deprecated env 提示（655–656）；基线 `pim:_ensure_env_file` 在 `.env.example` 缺失时写入旧 `AI_PROCESSING_ENABLED/ENRICH_*`，补丁移除并由 `backend/tests/test_pim_cli.py:test_minimal_env_fallback_does_not_reintroduce_legacy_ai_switches` 保护。 |
| PIM_AI_HARD_DISABLE 部署级硬停 | 已实现 | 配置审查 | 部署行为外部阻塞 | `backend/.env.example:62`；policy hard-disabled 分支。 |
| 主观评分 Shadow、权重 0 | 已实现 | 代码审查 | 生产 Shadow 成本/质量外部阻塞 | `score_subjective.py` 191：`shadow_weight: 0.0`。 |

### 3.4 M2：真实质量闭环

| 验收点 | 代码状态 | 本次自动化验证 | 真实验收 | 精确证据与结论 |
|---|---|---|---|---|
| M2-01 Core Eval 1.0 runner/门禁 | 已实现框架 | release generator 实际 RC=1/NO_GO | **真实 ≥200、≥10 来源、人工标注阻塞** | `backend/scripts/run_formal_eval.py:evaluate_core`（187 起）；`generate_release_eval_artifact.py` 56–66。 |
| M2-02 Event Eval 1.0 runner/难例 adjudication | 已实现框架 | 无数据不能运行正式结果 | **真实 ≥50 簇/≥200 pair、双标阻塞** | `run_formal_eval.py:_event_errors/evaluate_event`（218–438），难例必须 adjudication。 |
| M2-03 Core/Event/Ranking/Calibration 指标 | 已实现计算 | 编译通过 | 无真实数据时结果无发布意义 | `backend/app/domains/eval/metrics.py:binary_classification_metrics/ranking_metrics/calibration_metrics/cluster_metrics`。 |
| M2-04 Quality Shadow 安全契约 | 已实现框架 | 编译通过 | **0 天生产 Shadow** | `backend/scripts/run_quality_shadow.py:build_shadow_report`，108–109 固定 `shadow_only=true`、`production_affected=false`。 |
| M2-05 observation/adjudication | 已实现 | 选定 M2/API 回归 pytest 通过 | 人工队列积累外部阻塞 | `backend/app/interfaces/http/events.py` 376–448；`models/score_feedback.py`。 |
| M2-06 Release Eval Artifact | 已实现且 fail-closed | **实际生成 NO_GO，RC=1** | 正式数据、Shadow、性能、approver 阻塞 | 阻塞项实测：formal missing、Core<200、Event<200 pairs、shadow missing、performance missing、approver missing。 |
| M2 退出：dataset/hash/manifest/CI/release diff 完整 | 未满足 | 当前 artifact 正确 NO_GO | **外部阻塞** | 附件无正式 dataset/manifest/report；不可标“待验收/完成”。 |

### 3.5 M3A：Event 稳定内核与在线归组

| 验收点 | 代码状态 | 本次自动化验证 | 真实验收 | 精确证据与结论 |
|---|---|---|---|---|
| 稳定 ID/唯一 active membership/生命周期 | 已实现机制 | 编译/迁移通过 | 连续 ID churn 外部阻塞 | `backend/app/domains/events/engine.py:uuid7_hex`（48）、`assign_content`（637）；0037 的 membership/partial unique schema。 |
| Event Signature v1 | 已实现 | 选定 M3 回归 pytest 通过 | 词典/多语言质量外部阻塞 | `backend/app/domains/events/signature.py`。 |
| 多阶段候选召回 | 已实现 | 选定 M3 回归 pytest 通过；正式性能/召回未执行 | Recall@K/P95 外部阻塞 | `engine.py:recall_candidates`（329）。 |
| Pair classifier/动态阈值/hard conflicts | 已实现 | 选定 M3 回归 pytest 通过；真实难例未执行 | Wrong/Missing Merge 外部阻塞 | `engine.py:_hard_conflicts/_effective_threshold/_classify`（155–311）。 |
| Duplicate/canonical/source independence | 已实现机制 | 编译通过 | ownership/syndication 数据外部阻塞 | `engine.py:_duplicate_event_ids`；`source_independence.py`。 |
| Event 状态与标题事实保守性 | 已实现机制 | 正式人工高风险集缺失 | **人工数据阻塞** | `engine.py:_safe_title`（413）。 |
| Canonical Snapshot/Today 同版本 | 已实现机制 | 迁移通过 | 默认 read 不能切换 | `engine.py:_refresh_event_and_snapshot`（472）、`shadow.py:build_v1_today_cards/freeze_digest_snapshot_refs`。 |
| API、alias、operation、merge/split/revert | 已实现 | 编译通过 | 人工运营验收外部阻塞 | `interfaces/http/events.py`；`operations.py:resolve_event/merge_events/split_event/set_event_lifecycle/revert_operation`。 |
| Today 不依赖 HourlyDigest 为真相源 | v1 路径满足；默认仍 v0 | 代码审查 | 需正式 gate 后切换 | `repository.py:list_today_highlights` 与 `shadow.py`；不得把 preview 当默认切换。 |
| M3A 退出指标 | 未满足 | 无正式数据 | **外部阻塞** | Missing Merge <8%、Wrong Merge <3%、连续 7 天 ID Churn 均无证据。 |

### 3.6 M3B：Event 演化、重平衡与灰度

| 验收点 | 代码状态 | 本次自动化验证 | 真实验收 | 精确证据与结论 |
|---|---|---|---|---|
| 有界 rebalance/checkpoint/closed 隔离 | 已实现机制 | 正式 benchmark 未复现 | 真实 workload/锁等待外部阻塞 | `backend/app/domains/events/rebalance.py:run_rebalance`（53）、light/deep（237/252）。 |
| Merge/Split/回滚不重写稳定 ID | 已实现机制 | 编译通过 | 大样本个人状态验收外部阻塞 | `operations.py`。 |
| Snapshot diff/失败保留旧版本 | 已实现机制 | 选定 Snapshot/Event 回归 pytest 通过；真实序列未执行 | correction/retraction 真实序列阻塞 | `engine.py:_facts_fingerprint/_change_type/_refresh_event_and_snapshot`。 |
| 后台 durable event_assign/lifecycle/rebalance | 已实现大部 | 编译通过 | 调度长稳外部阻塞 | `domains/ingest/finish.py`、`backend/app/scheduler.py`。 |
| v0/v1 Today diff audit | 已实现框架 | 选定 Event API 回归 pytest 通过 | **0 天生产 Shadow** | `shadow.py:record_today_diff_audit`（117）；固定 shadow flags（约 176–177）。 |
| Read switch 双门控 fail-closed | 已实现 | 配置审查 | Gate 未批准 | `backend/app/domains/events/config.py:event_v1_today_read_enabled`（75–81）要求 `EVENT_V1_TODAY_READ` 与 `EVENT_V1_READ_GATE_APPROVED` 同时 true；`.env.example` 160–164 默认 false。 |
| P3 实验默认关闭 | 符合 PRD | 配置审查 | 四周前置条件未满足 | 不扩大 M5/M6/P3；当前不应施工/启用。 |
| M3B 退出：≥7 天 Shadow/人工抽样/ID Churn | 未满足 | 无可携 artifact | **外部阻塞** | 台账写“0 天 Production Shadow”与源码门禁一致，状态必须继续阻塞。 |

### 3.7 M4：付费源与产品闭环

| 批次 | 审计判定 | 补丁后状态 | 精确证据与结论 |
|---|---|---|---|
| M4-01 Paid-source Matrix | **基线行为错误，已修复** | 仓库内核心语义已改善；生产长稳仍阻塞 | 基线 `paid_matrix.py` 49–55：先按正文判成功，HTTP 500 + 可读正文时 `failure_code` 仍为空；72 行把当前结果写成 1/0“7d rate”。补丁后当前 `record_paid_source_result` 49–96 同时要求 2xx+可读正文，查询真实滚动 7 天，并保留历史 `last_readable_success_at`；API 63–70 不再模糊返回 success。 |
| M4-02 恢复演练/MTTR | **台账误报、部分实现** | 未修成假演练；仍阻塞 | `trigger_session_expiration/ack/complete`（102–141）只创建/修改审计时间戳，没有真正使 cookie 失效、触发告警、人工登录、重新抓取并验证恢复。MTTR≤10 分钟必须真实演练。 |
| M4-03 Local Capture Worker | **台账误报；基线 P0 安全缺陷** | 安全 envelope 已修；Worker/入库仍未实现 | 基线 `local_capture.py` 22、25–30、47、55–60、70、86–96。补丁后当前 26–95 nonce/HMAC/TTL，100–144 server allowlist，147–168 active device，170–219 DB 唯一防重放；0039 迁移 22–59。仍只有 audit，函数 docstring 178–183 明确 browser worker/content-ingest 是后续步骤；前端无 extension/content script。 |
| M4-04 Daily Canary | **台账误报、未接线** | 仅幂等记录器；仍阻塞 | `run_daily_canary_for_source` 当前 144–201 明确 caller 必须执行真实 authenticated fetch，函数不是 scheduler；`backend/app/scheduler.py` 无 canary 注册；HTTP `/daily-canary` 接收调用方 `sample_body`。不能称“每日探针调度已完成”。 |
| M4-05 Auth ZIP hardening | **基线 helper 未接真实路由，已修复** | 仓库内工程可认为完成；仍建议真实威胁测试 | 基线真实路由 `auth_assistant.py` 212 整体 `read()`，303–319 直接 `archive.read(profile_path)`；补丁后 206–215 使用压缩包上限，305–327 进入 `parse_auth_export_zip`。`auth_zip.py` 17–22 限额、29–49 path/type、52–106 metadata、109–133 bounded reads、136–179 manifest/profile 解析。 |
| M4-06 Topic 一级闭环 | **台账误报、部分实现** | 后端不变量已改善；一级 UI 缺失 | 补丁后 `topic_service.py` 25–32 校验，60–68 预验证 Event，70–99 并发安全，110–136 用 `event.source_names` 统计覆盖；但 frontend route/menu/page 搜索无 Topic 一级入口，仅 API/types 存在。 |
| M4-07 周报/月报 Brief | **台账误报、部分实现** | 不可变/lineage/modality 已修；产品闭环缺失 | 基线 `brief_service.py` 65–71 会覆盖已发布 row，48–55 接受任意 ID，86/100 分两次 commit，117–123 可无审计 override。补丁后 38–62 校验真实 Snapshot lineage，103–178 immutable/idempotent/单事务，181–207 受审计 override。仍无真实生成器、调度、列表/详情读取 API、前端周/月报入口。 |
| M4-08 Modality Lattice | **基线 fail-open，已修复** | 仓库内 invariant 更可信；真实案例长稳阻塞 | 基线未知 modality 静默变 `reported`；补丁后 `brief_service.py:_modality` 15–20 fail-closed，23–35 不允许下游提高确定性，违规 audit 与 Brief 同一事务。 |
| M4-09 Curated/Full + 导出迁移 | **基线 dead/unwired，已修复** | API/UI/导出边界已接线；正式前端测试未执行 | 基线 `events.py:get_event_detail` 452–466 无参数，`repository.py` 原始 timeline 全量返回，`contents_crud.py` 234–236 只查 legacy membership。补丁后 `events.py` 453–470 接 `full_reports`；`repository.py` 424–480 默认最多 3 条、显式 full 全量，566–568 暴露模式/总数且保留原诊断 extra；前端 `EventDetailPage.tsx` 14–19、102–114 显式展开；`contents_crud.py` 231–237 支持 v1 membership。`backend/app/platform/export/markdown.py:MarkdownExporter.render_event_markdown` 的 Event 导出只包含摘要、时间线、来源与原文链接；另 `domains/events/presentation.py:export_event_to_markdown` 也对 `is_paid_source` 滤除全文。 |
| M4 退出：MTTR≤10 分钟、Brief 可逐层回溯、Topic 不污染 Event ID | **仅第三项后端结构基本满足；整体未验收** | 继续阻塞 | MTTR 无真实演练；Brief 仅有写入 service 且无产品生成/读取闭环；Topic association 不改 Event ID，但缺一级产品入口和真实流量校验。 |

## 4. 重点发现（按优先级）

### P0-01 Local Capture 安全契约名义存在、实际 fail-open

**风险**：任意调用者可自带 allowlist 或不带 allowlist直接通过；公开 salt 可离线生成 token；同一秒 token 可预测；未来 5 分钟 token 可通过；已撤销/不存在设备仍可提交；同 token 可重复消费。

**基线证据**：

- `backend/app/domains/fetch/local_capture.py:22`：硬编码 `SECRET_SALT`；
- `25–30`：token 无 nonce，同 device/origin/second 确定；
- `47`：`abs(now-created)` 接受未来时间；
- `55–60`：无 allowlist 默认 `True`，且 substring 匹配；
- `63–70`：allowlist 由请求方传入；
- `86–96`：只 insert audit，无设备状态校验、无唯一冲突处理。

**修复**：见补丁中的 `local_capture.py`、`paid_matrix.py` model、0039 migration、HTTP schema 和负向测试。没有把浏览器 worker 或真实内容入库伪造出来。

### P0-02 Auth ZIP 的安全 helper 没有保护真实导入入口

**风险**：ZIP bomb、超大上传、manifest 引用任意 archive member、重复 entry、encrypted/special member 等可绕过独立 helper，直接进入 Auth bundle import。

**基线证据**：`auth_assistant.py:204–214,303–325`。真实路由无压缩包上限，直接 `archive.read()`；`auth_zip.py` 只做 metadata 检查且没有被路由调用。

**修复**：真实入口采用 50 MiB compressed 上限和同一 fail-closed parser；member 实际读取受 10 MiB 限制并核对 `file_size`，拒绝 backslash/absolute/traversal/drive、duplicate、encrypted、symlink/special、单项/总体/压缩比异常。

### P0-03 Paid-source “可读成功”与“7 天成功率”均可造假

**基线行为**：HTTP 500 + 长正文会被记为成功；`success_rate_7d` 只是当前一条的 1/0；一次失败把 `last_readable_success_at` 置空；API 固定返回 `status=success`。

**修复**：HTTP 必须 2xx 且正文可读；滚动 7 天从审计表计算；失败保留历史最近成功时间；API 返回真实 failed/success。

### P0-04 M0/M2 无真实数据时必须继续 NO-GO

此次实际执行：

- `check_bootstrap_eval.py`：RC=1，`core_records=0`、`event_pairs=0`、`ok=false`；
- `generate_release_eval_artifact.py --enforce`：RC=1，`decision.result=NO_GO`。

这不是缺陷，而是正确的 fail-closed 行为。禁止用现有 4 行 synthetic fixture、mock 或自建 harness 填绿。

### P1-01 M1 后处理幂等键忽略 fingerprint

基线 `_pipeline_identity("finish:<pipeline>:<fingerprint>")` 只取 `<pipeline>`，使同一内容后续实质更新复用旧 succeeded key。已修复并补测试。

### P1-02 Brief “immutable” 实际原地覆盖，lineage 可伪造

基线代码与 PRD/表注释直接矛盾。已改为：真实 Snapshot FK 语义校验、lineage 固化 event/version/generator、完全相同请求幂等返回、任何内容差异冲突、唯一键并发恢复、Brief+audit 单事务。

### P1-03 Daily Canary 没有 Scheduler，也没有真实 fetch

30.3 M4-04 写“每站每日 Canary 探针调度”，但搜索整个 scheduler/platform 仅找到 domain 记录函数和手动 POST。补丁故意保留 docstring 说明“caller must perform real authenticated fetch”，避免把 sample body 伪装为探针结果。

### P1-04 M4 Product 闭环缺失

- Local Capture：无浏览器 extension/content script，无 ReaderDocument→Content ingest；
- Topic：无一级前端 route/menu/page；
- Brief：无真实 generator/schedule/list/get UI；
- Recovery drill：无真实 session expiry/login/re-fetch；
- Daily Canary：无 scheduler/真实登录态抓取。

因此 M4 不能写“9/9 工程完成”。

### P1-05 curated/full 在真实 API 未接线

原代码的 curated helper/测试不能证明真实 `/api/events/{id}` 边界。补丁将默认最多 3 条、显式 full、前端展开与 v1 导出真正接到生产路由，并补 API/UI tests。

### P1-06 `./pim` 回退路径重新引入旧 AI 产品开关

当 `.env.example` 缺失时，基线 `pim:_ensure_env_file` 会生成 `AI_PROCESSING_ENABLED=false`、`ENRICH_SUMMARY_ENABLED=false`、`ENRICH_TRANSLATE_ENABLED=false`。这与 PRD 规定的 `system_settings` 产品控制面和仅保留 `PIM_AI_HARD_DISABLE` 部署级硬停相冲突，也会让不同安装路径产生不同配置语义。补丁删除这些旧变量，仅保留非 AI 的最小运行配置，并新增 CLI 回归测试。

### P2-01 30.3 证据不可复核

台账引用：后端 `1620/1630/1638/1654/1660/1678 passed`、前端 `121/124 passed`、真实 Local DB 升降级、`~/.pim` 备份、生产数据库计数、100k benchmark、0.036s、coverage 等。附件中：

- 不含 `.git`；
- 不含 `PIM_Next_Stage_Upgrade_2026-07-22_Construction/`；
- 不含 `~/.pim` artifact/backup/数据库；
- 不含正式 Eval/Bootstrap 数据；
- 不含 Shadow/performance/release GO artifact。

这些陈述可能来自此前环境，但**不是当前附件可携、可复核证据**，应标“历史外部证据，需重新附 artifact/CI URL/签名报告”，不能作为本次独立验收结论。

### P2-02 架构文档违反 CLI HTTP-only 边界

`docs/ARCHITECTURE.md` 基线 13–14 写 CLI 与后端“全部共享同一份 SQLite”；同文其他章节和代码要求 `pimctl` 仅 HTTP。补丁已改为 SQLite 仅由后端持有，CLI 只经 HTTP API。

## 5. 30.3 台账审计

### 5.1 可保留的诚实表述

- M0：工程止血与 fail-closed 框架存在，真实 Bootstrap 阻塞；
- M1：工程机制存在，生产 no-loss/SIGKILL/provider/7d 长稳待验收；
- M1A：工程机制存在，`./pim` 旧 AI 开关回退已修；真实 provider 状态待验收；
- M2：工程链路存在，正式数据/Shadow/性能/审批阻塞，当前 NO-GO；
- M3A/M3B：工程链路存在，正式 Event Eval 和 ≥7d Shadow 阻塞，read gate 不得批准；
- M4：生产付费源和长稳仍需外部数据。

### 5.2 必须改正的台账内容

1. `PIM-M4` 主行不应是“9/9 工程批次完成”，应改为：
   - **进行中/阻塞（安全与不变量修复完成；产品接线和生产验收未完成）**；
   - 工程进度不宜用 9/9，建议拆为“仓库内安全/数据契约 5/9；产品闭环 0/4；生产验收 0/3”。
2. M4-02 不得标“工程已实现”：当前只是审计状态机，不是真实恢复演练。
3. M4-03 不得标“Local Capture MVP 已实现”：当前补丁后也只有安全接收 envelope，仍无 worker/ingest。
4. M4-04 不得写“探针调度”：当前无 scheduler 注册或真实 fetch。
5. M4-06 不得写“一级入口”：只有后端 API，无前端一级入口。
6. M4-07 不得写“周报/月报已交付”：只有写入 service/API，无 generator、调度、读取产品面。
7. M4-09 基线不应写完成；补丁后可写“仓库内 API/UI/导出边界已实现，正式前端门禁待依赖恢复后验证”。
8. 所有历史 pass count、coverage、真实 DB migration、备份、benchmark 必须附当前可访问的 CI artifact、日志、checksum；否则标“不可从源码快照复核”。
9. M1A 应补记 `./pim` 最小 `.env` 回退缺陷及修复，明确产品 AI 开关只由 `system_settings` 管理，部署层只允许 `PIM_AI_HARD_DISABLE`。
10. 30.3 链接的施工文档目录在附件中缺失，应恢复受管文档或删除失效链接。

## 6. 测试与验证结果

### 6.1 成功执行

| 命令/检查 | 结果 |
|---|---|
| 附件 SHA-256 | 与用户给定值完全一致 |
| `unzip -t` | 通过，876 个文件 |
| `python -m compileall -q app scripts tests` | 通过 |
| `python scripts/check_domain_imports.py --phase=5` | 通过：phase 5 clean，401 files scanned |
| `python scripts/check_ble001_budget.py` | 通过：`0 <= 188` |
| 选定 backend pytest 回归 | **87 passed**；覆盖架构边界、M0/M1/M1A/M2/M3/M4、Event API、正式评测 fail-closed 等选定用例 |
| `git diff --check` | 通过 |
| changed-Python AST literal duplicate-key check | 通过；审计中发现并修复一次 `extra` 重复键覆盖后重跑为 none |
| `check_bootstrap_eval.py` | RC=1，按设计 fail-closed；Core/Event 正式文件缺失 |
| `generate_release_eval_artifact.py --enforce` | RC=1，按设计 `NO_GO` |
| Alembic fresh `upgrade head` | 通过，head=`20260729_0039` |
| Alembic `0037→0038→0039→0037→0038→0039` 往返 | 通过 |
| SQLite `PRAGMA integrity_check` / foreign key check | `ok` / 无违规 |
| Local Capture unique replay index | `uq_local_capture_task_token_hash` 存在且 unique |
| package.json/package-lock 根依赖映射 | 一致 |
| `openapi.json` / `package-lock.json` JSON parse | 通过 |
| 补丁对重新解压的干净附件 `git apply --check` | 通过 |
| 补丁实际应用后 `compileall` | 通过 |

Alembic 过程中已有旧迁移对 SQLite expression index reflection 发出 SAWarning，但未导致迁移失败。第一次 downgrade 命令曾误写不存在的 revision `20260728_0037`，立即更正为真实 `20260724_0037` 后完整往返通过；该输入错误不是仓库缺陷。

### 6.2 选定测试环境的限定

为让同步、不会打开 async engine 的选定项目测试完成收集，审计环境使用了一个**审计专用、仅满足导入的 `aiosqlite` stub**。它的 `connect()` 明确抛错，未用于模拟数据库行为。87 个通过项属于仓库正式 pytest 用例的选定回归，不是自创 pass count；但仍不能替代正常锁定依赖下的全量 pytest。

另有外部定向 harness `targeted-audit: PASS`，覆盖 Local Capture allowlist/device/replay、HTTP 500 与 7 天成功率、same-day canary 幂等、Topic 覆盖、Brief lineage/immutable/modality、Auth ZIP 负向路径、postprocess fingerprint。该 harness 只作补充证据，不计入 87 个 pytest，也不能替代生产验收。

### 6.3 未执行或未完整执行

| 要求 | 结果 | 原因 |
|---|---|---|
| `ruff check app` | 未执行 | 当前环境无 `ruff`；离线依赖安装受网络/registry 条件限制 |
| backend 全量 pytest | **未完成** | 收集到 12 个 collector/parser 相关模块时缺 `feedparser`；`.pytest_cache` 记录的 12 个模块包括 RSS/website/X 等测试。禁止把 87 个选定通过项描述成全量通过 |
| PostgreSQL persistence contract | 未执行 | 未提供 PostgreSQL service；SQLite 迁移往返不能替代 PostgreSQL 契约测试 |
| `npm run lint` | RC=127 | `eslint` 不存在，`node_modules` 未安装 |
| `npm run test -- --run` | RC=127 | `vitest` 不存在 |
| `npm run build` | RC=2 | React/Vite/type declarations 等依赖不存在；错误以模块缺失为主，不能据此判断源码 build 成败 |
| `npm ci --offline` | 失败 | npm cache 不完整；网络不可用 |
| Browser E2E | 未执行 | 无已安装前端依赖和可用浏览器测试环境 |
| Rust/Tauri test | 未执行 | Tauri/Rust 依赖与实机 Keychain 环境未准备 |
| security/secret/dependency scan/SBOM | 未完整执行 | 对应工具和依赖不可用；仅完成源码人工安全审计与锁文件一致性检查 |

因此，本报告只主张“选定回归 87 passed + 迁移/门禁/静态检查结果”，**不主张 backend 全量、frontend 门禁、E2E 或生产验收通过**。补丁应在项目正常锁定依赖环境中重新跑全部发布门禁。

## 7. 外部阻塞清单

这些项不能通过代码补丁“修成绿色”：

1. Core Bootstrap ≥50、Event Bootstrap ≥15 簇/50 pair 的真实脱敏、人工复核数据和 manifest；
2. Core Eval ≥200、Event Eval ≥50 簇/≥200 pair、双标/裁决、独立 test split；
3. 真实 Cloud provider 凭据下的 401/429/超时/不可达、调用次数和费用；
4. M1 accepted-job no-loss、SIGTERM/SIGKILL、queue full、DB transient、provider failure 和 7 天窗口；
5. M3 Recall/P95/Wrong Merge/Missing Merge、人工难例、跨日 continuity、连续 7 天 ID Churn；
6. v0/v1 Today ≥7 天且推荐 14 天 Shadow 和人工 diff 抽样；
7. 真实付费源 Cookie 连贯性、每日 authenticated canary、7 天数据；
8. 真实 session 失效→告警→人工重新登录→重新抓取的 MTTR 演练；
9. Local Capture cookie 不出本机的端到端证明、真实 browser worker/extension、device revoke 实机；
10. 周/月报真实生成、逐层 lineage 人工核查、分发/阅读 UI；
11. Release approver、性能 baseline、SLO 变化、安全扫描、secret scan、dependency review、SBOM、release notes。

## 8. 建议的 PRD/台账诚实标注模型

每个批次至少拆成三列，避免“代码存在=完成”：

| 维度 | 允许状态 | 例子 |
|---|---|---|
| 代码落地 | 未开始 / 部分 / 已落地 | route 是否真正调用 domain、UI 是否真正接线、migration 是否存在 |
| 自动化验证 | 未执行 / 失败 / 局部通过 / 全门禁通过 | 必须写实际命令、commit、artifact checksum；mock/fixture 明示 |
| 真实验收 | 未开始 / 外部阻塞 / 进行中 / 达标 | 真实数据、凭据、人工标注、生产 Shadow、7 天长稳、MTTR |

建议状态示例：

- M0：`代码落地=大部完成；自动化=依赖恢复后重跑；真实验收=Bootstrap 数据阻塞`；
- M1：`代码落地=完成（含本补丁）；自动化=未完整执行；真实验收=生产 no-loss/7d 阻塞`；
- M2：`代码落地=框架完成；自动化=fail-closed 正常；真实验收=未开始；发布=NO_GO`；
- M3：`代码落地=大部完成；自动化=未完整执行；真实验收=0 天 Shadow；read gate=关闭`；
- M4：`代码落地=部分；自动化=局部；真实验收=阻塞；9/9 声明撤销`。

## 9. 补丁说明

`pim_m0_m4.patch` 只包含此次确认必要的最小代码、测试、OpenAPI/types 和架构文档修复，不包含：

- 凭据、数据库、缓存、日志、测试输出或生成构建产物；
- 真实数据或伪造 Eval fixture；
- Git commit、push、PR、部署或线上配置；
- M5/M6 范围扩张。

主要修改文件：

- M1 幂等：`backend/app/platform/workers/postprocess_jobs.py`；
- M4 Local Capture/Auth ZIP/Paid Matrix：`domains/fetch/*`、HTTP routes、models、0039 migration；
- M4 Topic/Brief：domain services、models、tests；
- M4 curated/full/export：Event repository/API、contents export、frontend page/service/types/tests；
- M1A 控制面：顶层 `pim` 与 `backend/tests/test_pim_cli.py`；
- 边界文档：`docs/ARCHITECTURE.md`。

补丁已对重新解压的干净附件执行 `git apply --check` 和实际 apply，并在应用后完成 Python compileall。由于附件没有 Git metadata，只能表述为：**补丁可干净应用到该附件所代表的 b17e71e 快照内容**；若真实 Git commit 的文件内容与附件不同，应先核对差异。

## 10. 最终意见

本项目不是“没有实现”，而是存在一个典型风险：**底座工程真实推进很多，但进度表把代码、测试外壳、历史环境证据和生产验收混在了一起。** 当前最重要的动作不是继续扩展功能，而是：

1. 合入并完整验证本补丁；
2. 把 M4 状态降回部分实现/阻塞；
3. 恢复可复核的施工文档、CI artifact、迁移日志和 checksum；
4. 安装真实 Bootstrap/Formal Eval 数据，保持 NO-GO 直至门禁满足；
5. 完成 Local Capture worker/ingest、Daily Canary scheduler+真实 fetch、Topic/Brief 一级产品闭环；
6. 再进行真实付费源、MTTR、7 天 Shadow/长稳验收。

在这些工作完成前，不建议批准 M0–M4 总体完成，也不建议打开 Event v1 普通 UI read gate。
