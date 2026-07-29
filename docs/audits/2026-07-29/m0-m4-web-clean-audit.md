# M0–M4 与 Web Clean 独立实现审计

- 审计日期：2026-07-29（SGT）
- 源码基线：`main` @ `b17e71ee0715cace333f6e2da3adfb1b29f9a5ae`
- 基线关系：`main...origin/main [ahead 3]`
- 审计范围：主升级 PRD 的 M0、M1、M1A、M2、M3A、M3B、M4；Web Clean PRD 的 FR-1–FR-10 与 M0–M4
- 变更权限：仅本地工作树；未提交、未推送、未建 PR、未部署、未迁移真实数据库

## 1. 可复现源码包

| 项目 | 值 |
|---|---|
| 文件 | `/tmp/PIM_M0-M4_WebClean_Audit_b17e71e.zip` |
| ZIP 字节数 | 2,317,296 |
| ZIP SHA-256 | `fb6f09456496134e7217cb1b8352acc5e394b2615f75160cfc26ae07c1484fe2` |
| ZIP 条目数 | 982 |
| 未压缩字节数 | 7,723,281 |
| 完整性 | `unzip -t` 通过 |

打包采用 `git archive HEAD`，另外只加入两份指定 PRD。排除 `.git`、`node_modules`、构建产物、缓存、数据库、运行状态与浏览器状态。上传前对解压树扫描私钥、JWT、API Key、Token、Cookie、`.env` 等模式；仅发现空值 `.env.example`、代码中的 cookie 字段名和测试占位值，没有发现可用凭据。

## 2. 外部高级工程师会话与原始交付物

- 主升级 M0–M4：<https://chatgpt.com/c/6a695fbf-349c-83ea-b20b-b79c30b56b9a>
- Web Clean：<https://chatgpt.com/c/6a69602d-0190-83ea-831e-dc73e2c1062b>

两条会话使用同一份已校验源码包，但任务说明和上下文相互隔离。外部结论只作为线索；本文状态以本地源码复核和独立测试为准。浏览器实际显示账号方案为 ChatGPT Plus，并非可由 Codex 证明的 Pro。

| 外部交付物 | 字节数 | SHA-256 |
|---|---:|---|
| `external/pim_m0_m4_review.md` | 41,542 | `d673123d28d3e7d5a869727de99bb31f7daa63883a47fc105e5285ceab0e14e2` |
| `external/pim_m0_m4.patch` | 120,026 | `feff55fe28b2b506d8911fe148203727ee17892634c02c4eba93ffb1b6d8a62f` |
| `external/pim_m0_m4_corrected.patch` | 15,514 | `e012df8bd17db9b39a154701da1fed686b008efff271bcfbc5257abb5667ecc7` |
| `external/pim_web_clean_review.md` | 30,481 | `a8326b666c5bcf444c588b684b2782ba37c77c4709944edcf209df12b77e7112` |
| `external/pim_web_clean.patch` | 179,231 | `b50f1e6948feb45788341d4afb7368edf5d210f78ef4989f14406dd3f1af226c` |
| `external/pim_web_clean_missing_files.patch` | 28,193 | `82bee6e7a3cb2c9136477a00869f47a8a7764ec8b7fa0a722f8eb13f7365fc41` |
| `external/pim_web_clean_release_gate_correction.patch` | 5,134 | `99f34a7c8e48eeb89a795eb66963a020f3b8916a23fa035a3aa9850d82b42190` |

## 3. 总结论

本次已把仓库内可确定、可自动验证的工程缺口落地，并同步在两份 PRD 标注；但不能把两份 PRD 标成“生产验收全部完成”：

1. 主升级 M0–M3 的工程骨架和自动化门禁较完整；Bootstrap/Formal 数据集、人工标注、真实 Production Shadow、7 天长稳及审批证据不存在，release gate 继续 fail-closed。
2. M4 的安全和服务端工程能力显著补齐：Local Capture envelope、真实 Auth ZIP 导入、Paid Matrix、Topic 关联、Brief lineage、curated/full 与付费全文过滤均有实现和测试。但 Daily Canary 的真实抓取/调度、Local Capture Extension/ingest、Topic 一级 UI、Brief 生成器/UI 仍未实现。
3. Web Clean 的标准化、Shadow DOM、结构化抽取、模板/过滤、Markdown、可解释入库、诊断、Formal/Shadow 工具与 HMAC release provenance 已落地；正式 fixtures/人工标签、真实站点质量、7 天报告和审批仍缺失，因此保持默认关闭，M5 为 NO_GO。
4. 本地全量自动化、迁移、构建和模拟浏览器 E2E 已通过；它们证明落地路径没有已知回归，不等同于真实生产站点、付费账号或用户数据验证。

## 4. 主升级 PRD 追踪矩阵

| 阶段 | 工程状态 | 自动化证据 | 尚未满足/外部阻塞 |
|---|---|---|---|
| M0 | 4/6 工程止血能力已接线 | StorageResult、missing content、durable FetchJob、Web/Tauri bootstrap 测试 | Core/Event Bootstrap 数据集与人工标注缺失；门禁按预期失败 |
| M1 | 9/9 工程链路存在 | durable lease/CAS、drain、scheduler ledger、outbox、lineage、write queue、双 profile contract、Event ADR | 无生产 accepted-job no-loss、SIGKILL/provider 故障和 7 天 SLO 证据 |
| M1A | 7/7 工程链路存在 | AI policy、cache/预算/并发/资格与前端状态测试 | 无真实 Cloud provider 401/429/不可达观察；发布安全总门禁未完成 |
| M2 | 6/6 工程框架存在，发布 NO_GO | formal runner、质量 Shadow、adjudication、release artifact fail-closed | Core ≥200、Event ≥50 簇/≥200 pair、双标/裁决、7 天 Shadow、性能与审批缺失 |
| M3A | 9/9 工程链路存在，默认 Shadow | stable ID、Signature、召回/分类、Snapshot/Today、API/观测测试 | 正式 Event Eval、真实跨日 continuity/ID churn/Assignment P95 未验收 |
| M3B | 01–07 工程链路存在；08 按门禁关闭 | rebalance、operation/revert、Snapshot diff、双跑与双开关读门禁 | 0 天 Production Shadow；普通 UI 不得切 v1；P3 未施工符合约束 |
| M4-01/02 | Paid matrix/恢复审计原语已加强 | 可读正文、权利来源、状态变更和恢复定向测试 | 无真实付费源、Cookie 连贯性和人工恢复演练 |
| M4-03 | 安全 envelope 已实现，产品链路部分实现 | 服务端 source policy、purpose-bound installation key、时效/origin/DB unique replay/input caps 回归 | 无 Extension、host permission 与受信 token 发放；无 worker/ingest 产品闭环 |
| M4-04 | 未接线 | `run_daily_canary_for_source` 单元原语 | 不抓取 Source；API 接收 `sample_body`；Scheduler 无任务 |
| M4-05 | 核心工程导入已实现 | 受保护 ZIP route、manifest/profiles JSON 导入、Bomb/Slip/Symlink/encrypted/duplicate/unexpected-entry 限制 | 未用真实浏览器导出包做生产 E2E |
| M4-06 | 服务端核心已增强、产品仍部分实现 | 并发安全 Topic create/associate、coverage/timeline detail、Event ID 不变 | 没有完整 CRUD/filter 与前端一级入口 |
| M4-07/08 | 服务端核心已增强、产品仍部分实现 | Event Snapshot lineage、period lock、modality/publication、并发幂等 | 没有周/月报真实生成器、列表/发布 UI 和生产事实样本 |
| M4-09 | 核心过滤已实现 | curated/full 语义、付费全文 Markdown 导出过滤 | 仍需真实权利元数据与历史个人状态迁移验收 |

## 5. Web Clean 追踪矩阵

| 需求 | 状态 | 已落地 | 未验证/缺口 |
|---|---|---|---|
| FR-1 HTML 标准化 | 工程已实现 | 危险/噪声节点、属性、URL、trace；base/noscript/lazy media/无效 selector/嵌套 decompose 防护 | 正式多站点 fixture 质量 |
| FR-2 Shadow DOM | 核心工程已实现 | bounded recursive open-root 展开、深度/节点/输出上限、slot 分配内容、总超时与 timeout marker | 真实复杂站点与 closed shadow root |
| FR-3 结构化优先 | 工程已实现 | JSON-LD/@graph/Article 合同、候选与降权 | 正式站点 metadata 准确率 |
| FR-4 模板 | 引擎已实现、模板数据阻塞 | metadata template、trigger/validation/render/probe、安全 regex | 5–10 个经真实样本验收的内置模板与效果数据 |
| FR-5 Filters DSL | 工程已实现 | allowlist filter、参数/输出边界、fail-closed、selector/regex 限时 | 正式 adversarial/站点样本 |
| FR-6 候选评分 | 工程已实现 | old/structured/template/generic 候选、过滤原因和 explainable trace | 正式阈值标定 |
| FR-7 Markdown | 工程已实现并修复接线 | converter/golden tests；启用链路持久化 `article_markdown` | 大样本 Reader/exporter 回归 |
| FR-8 入库/metadata | 工程已实现 | source `off/shadow/write`、production eligibility、bounded metadata、input hash | 真实回退观察 |
| FR-9 Health/Debug | 核心诊断已实现 | Reader/Fetch Health/Probe/support bundle 展示 profile、候选与失败原因并脱敏 | 完整产品化交互和真实支持流程 |
| FR-10 Eval/Shadow | 工程闭环已实现、外部验收阻塞 | formal runner、fixture/manifest hash、HMAC provenance、shadow runner、release gate/CI fail-closed | 正式数据、真实 7 天报告、性能和 approver |

### Web Clean 里程碑状态

| 里程碑 | 诚实状态 |
|---|---|
| M0 | 阻塞：合同/runner 已有；30 fixtures、manifest、baseline 缺失 |
| M1 | 核心工程已实现，待正式数据验收 |
| M2 | 引擎已实现；经真实样本验收的内置模板和产品化 preview 缺失 |
| M3 | 核心工程已实现，待真实复杂站点验收 |
| M4 | 工程闭环已实现；正式数据、真实 7 天证据和审批缺失 |
| M5 | NO_GO；默认开关不得开启 |

## 6. 实际本地修改

1. Local Capture：服务端派生付费/认证源策略、active paired device、purpose-bound installation key、未来/过期/origin 验证、数据库唯一防重放、输入上限及 `0039` 迁移。
2. Auth Assistant：真实受保护 ZIP 导入 route；有界 manifest/profiles JSON 解析；防 Zip Bomb/Slip、symlink、加密、重复与意外条目。
3. M4 领域：Paid Matrix 状态与权利来源；Topic 并发关联和 coverage/timeline；Brief Event Snapshot lineage、modality/publication 状态和并发幂等；Event identity；curated/full API 与付费全文导出过滤；CLI AI 环境回退。
4. Web Clean：HTML 标准化、结构化/候选/模板/过滤改进；selector/regex 限时；有界递归 Shadow DOM 与 slot；Markdown 持久化；source `off/shadow/write` 与 production eligibility；Reader/Fetch Health/Probe/support bundle 可解释诊断。
5. 发布证据：正式 eval、shadow runner、HMAC provenance、输入 SHA 绑定、fail-closed release gate 与 CI；缺真实数据时明确 NO_GO。
6. 依赖和合同：增加 `regex`，修复锁文件冲突并重新解析；更新 Auth Assistant 锁；固定 `react-router-dom@7.18.2`；同步 OpenAPI 和生成的 TypeScript API。
7. 文档：更新架构说明、两份 PRD 状态及本审计报告；保留外部原始报告和补丁作为证据。

## 7. 要求外部工程师修正的问题

1. 主升级原补丁的 `0039` 迁移会删除重复的 immutable audit 记录；要求改为 fail-closed，并补充 Local Capture 输入上限。
2. 主升级 fresh-upgrade 测试仍断言旧 head `0038`；要求更新到 `0039` 并验证新列/唯一索引。
3. Web Clean 首次补丁引用但遗漏五个新文件（provenance、safety、shadow runner、release gate/Shadow DOM tests）；要求提供完整最小增量。
4. Web Clean release gate 首版既未实现 `web_clean_provenance_hmac_key` 配置，也让旧 unsigned GO fixture 继续通过；要求重新验证 HMAC、输入 SHA 绑定并 fail-closed。
5. 合并补丁后 `uv.lock` 出现重复 `regex` dependency/spec；本地 `uv lock --check` 捕获，外部确认原始锁不应重复，随后重新生成。

## 8. 独立验证结果

| 门禁 | 结果 |
|---|---|
| Backend Ruff | 通过 |
| Backend 架构依赖边界 | 通过，403 个文件无违规 |
| BLE001 异常预算 | 通过，`188 <= 188` |
| Backend 全量 pytest | `1788 passed, 6 skipped, 9 warnings`，coverage 72% |
| Web Clean release/shadow 定向测试 | 通过；缺正式报告时 enforce 按预期 NO_GO |
| Frontend lint / API types | 通过；生成结果 SHA-256 `01e43297ed11683f7666bdeeb598b7761a40815e846a41058176c700db93b3e1` |
| Frontend unit | 26 files，`132 passed` |
| Frontend production build | 通过 |
| Frontend Chromium E2E | `5 passed`；本地 Playwright mock/fixtures，不是生产验证 |
| Auth Assistant npm audit | 0 漏洞 |
| Auth Assistant build / Rust | 通过；Rust `3 passed` |
| Python lock / dependency audit | `uv lock --check` 通过；`pip-audit` 无已知漏洞 |
| Alembic isolated fresh | 空临时 SQLite → `20260729_0039 (head)`；integrity/FK/新列/唯一索引通过 |
| Alembic isolated roundtrip | `0039→0037→0039` 通过 |
| Release artifact enforce | 按预期 NO_GO：Core/Event Formal、样本、quality/Web Shadow、Web Formal、7 天、性能和 approver 缺失 |
| `git diff --check` | 通过 |

主前端 `npm audit --omit=dev` 仍报告 2 个 high，均来自 React Router RSC mode 的同一 CSRF 公告。项目使用 declarative `BrowserRouter`，不使用 RSC action/server runtime，当前路径不可达；`npm audit fix --force` 会建议降级/破坏性变更，因此未自动执行。该项作为依赖供应链风险保留，不宣称已修复。

## 9. 未验证风险与发布边界

1. 所有真实付费站点、真实登录态、生产用户数据、Cloud provider 故障、通知交付与人工恢复均未验证。
2. Core/Event/Web Clean 正式数据、双标/裁决、baseline、真实 7–14 天 Shadow/SLO、性能与审批证据缺失；统一 release gate 必须保持 NO_GO。
3. Daily Canary 调度/真实抓取、Local Capture Extension/worker/ingest、Topic 一级 UI、Brief 生成器/UI 仍是明确产品缺口。
4. Web Clean 的 closed Shadow DOM 本身不可遍历；正式模板和复杂站点兼容性只能通过后续真实数据验证。
5. React Router RSC 公告尚无适合当前技术栈的无破坏升级路径；如果将来启用 RSC，必须先升级/迁移并重新威胁建模。
6. 本次没有提交、推送、PR、部署、真实数据库迁移、线上配置或生产开关操作；所有实现仍只是当前本地工作树修改。
