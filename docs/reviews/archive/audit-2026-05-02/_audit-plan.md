# PIM 代码全面审计计划

> **执行方式：** 使用 superpowers:subagent-driven-development 或 superpowers:executing-plans 按模块执行。

**目标：** 对 personal-info-monitor 项目进行全面审计，评估代码逻辑性、功能完整性、工程合理性，输出问题清单与改进建议。

**架构速览：**
- 后端：FastAPI + SQLAlchemy(async) + SQLite + APScheduler，~120 文件，~19500 行
- 前端：React 18 + TypeScript + Ant Design + Vite，~90 文件，~6500 行
- CLI：Bash pim 脚本 + Python pimctl，~8 文件，~1400 行
- 测试：pytest 59 文件(11507 行) + Vitest/Playwright ~30 文件

**评级标准（每项审计）：**
- ✅ 良好：无需改动
- ⚠️ 轻微问题：建议改进，不阻塞功能
- ❌ 严重问题：影响正确性/安全性/可维护性，需修复

---

## 模块一：架构与分层设计

**关键问题：**
- 分层是否清晰（collectors → pipeline → processors → storage → API → frontend）？
- 模块间依赖方向是否正确（上层依赖下层，不反向）？
- ADR-001（本地单体）、ADR-003（凭证安全）、ADR-004（功能标志）决策是否落地一致？
- 模块职责是否单一（SRP）？

**要读的文件：**
- `backend/app/main.py`（498 行）— 应用入口、中间件、生命周期
- `backend/app/pipeline/coordinator.py`（234 行）— 流水线协调
- `docs/ARCHITECTURE.md`
- `docs/ADR-001-local-monolith.md`
- `docs/ADR-003-auth-credentials.md`
- `docs/ADR-004-feature-flags.md`

**审计清单：**
- [ ] main.py 启动逻辑：迁移、调度器、队列是否顺序正确？启动失败是否会 crash 而非静默继续？
- [ ] pipeline/coordinator.py：流水线各阶段是否有清晰的接口契约？错误是否向上传播还是被吞？
- [ ] ADR-001：单体设计是否有清楚的边界，避免成为 Big Ball of Mud？
- [ ] ADR-004：功能标志是否集中管理，还是散落在各处？
- [ ] services/ 和 tasks/ 是否有职责重叠？

**输出：** `audit/01-architecture.md`

---

## 模块二：认证与安全

**关键问题：**
- X-API-Key 认证是否正确且无绕过点？
- 引导令牌（Bootstrap Token）防 DNS rebinding 是否有效？
- 敏感凭证（API Keys、OAuth tokens）加密存储是否正确？
- SSRF 防护是否完整？

**要读的文件：**
- `backend/app/auth.py`（25 行）— API Key 验证
- `backend/app/utils/ssrf.py` — SSRF 黑名单
- `backend/app/utils/encryption.py` — Fernet 加密
- `backend/app/api/configs_api_auth.py`（349 行）— OAuth/API 凭证
- `backend/app/main.py` 中的 `/local-token` 端点和安全头
- `backend/tests/test_api_security_observability.py`（303 行）
- `backend/tests/test_ssrf_protection.py`
- `backend/tests/test_encryption_coverage.py`

**审计清单：**
- [ ] `auth.py`：是否使用 `hmac.compare_digest` 而非 `==`？所有受保护路由是否都注入了 Depends(verify_api_key)？
- [ ] `/local-token` 端点：Host 头验证逻辑是否完整？有无绕过方式（X-Forwarded-Host 等）？
- [ ] `ssrf.py`：私有 IP 黑名单是否完整（127.0.0.0/8、10.0.0.0/8、172.16.0.0/12、169.254.0.0/16、::1 等）？DNS 解析后是否再次验证 IP？
- [ ] `encryption.py`：密钥来源是否安全？有无硬编码密钥或弱密钥？加密算法是否有 IV 重用问题？
- [ ] `configs_api_auth.py`：解密凭证时是否有异常处理？错误响应是否泄露明文？
- [ ] CORS 配置：白名单是否过于宽泛？`tauri.localhost` 是否有潜在问题？
- [ ] 速率限制：每 IP + API Key 双维度是否都覆盖？绕过路径（`/livez`、`/local-token`）是否合理？
- [ ] 安全头（CSP、X-Frame-Options 等）是否正确设置、无误配？

**输出：** `audit/02-security.md`

---

## 模块三：数据采集流水线

**关键问题：**
- 五种采集器（RSS、Website、X/Twitter、YouTube、Podcast）是否健壮？
- 流水线（CollectorStage → NormalizerStage → AIStage → StorageStage）是否错误隔离？
- Playwright 浏览器池是否存在泄漏或超时问题？
- 去重逻辑是否准确？

**要读的文件：**
- `backend/app/collectors/base.py`（115 行）— 基础接口
- `backend/app/collectors/website.py`（849 行）— 最复杂采集器
- `backend/app/collectors/x_twitter.py`（647 行）
- `backend/app/pipeline/collector_stage.py`（137 行）
- `backend/app/pipeline/normalizer_stage.py`（171 行）
- `backend/app/pipeline/dedupe.py`（84 行）
- `backend/app/utils/browser.py` — Playwright 池
- `backend/tests/test_website_collector.py`（955 行）
- `backend/tests/test_pipeline_stages.py`（860 行）

**审计清单：**
- [ ] `collectors/base.py`：基础接口是否定义了超时、重试、错误返回的规范？各子类是否遵守？
- [ ] `website.py`：Playwright 使用后是否保证释放（try/finally 或 context manager）？并发控制是否有效？
- [ ] `x_twitter.py`：登录状态恢复逻辑是否有失效处理？GraphQL 解析是否防御 None 字段？
- [ ] `pipeline/coordinator.py`：某一阶段失败是否会中断整个流水线？还是允许部分成功？
- [ ] `normalizer_stage.py`：内容质量过滤标准是否明确？过滤是否过于激进（误杀）或宽松（垃圾入库）？
- [ ] `dedupe.py`：URL 规范化是否处理常见变体（trailing slash、query params、fragments、重定向后 URL）？
- [ ] 错误计数（source.error_count）：递增逻辑是否正确？阈值触发禁用是否有恢复机制？
- [ ] 采集并发（FETCH_CONCURRENCY）：是否有死锁或资源饥饿风险？

**输出：** `audit/03-pipeline.md`

---

## 模块四：AI 处理与摘要

**关键问题：**
- 摘要/翻译处理器是否正确处理多提供商（OpenAI、Anthropic、Google）？
- 流式翻译是否有正确的错误恢复？
- 小时摘要生成逻辑是否合理？内容选择算法是否公平？

**要读的文件：**
- `backend/app/processors/content_processor.py`（310 行）— 主控制器
- `backend/app/processors/summarizer.py`（410 行）
- `backend/app/processors/translator.py`（382 行）
- `backend/app/processors/keyword_matcher.py`（270 行）
- `backend/app/services/hourly_digest/synthesis.py`（379 行）
- `backend/app/services/hourly_digest/selection.py`（129 行）
- `backend/app/services/reader/streaming.py`（205 行）
- `backend/tests/test_processors.py`（794 行）

**审计清单：**
- [ ] `content_processor.py`：AI 处理是否在功能标志（AI_PROCESSING_ENABLED=false）关闭时完全跳过？
- [ ] `summarizer.py`：API 调用是否有超时和重试？失败时是否有降级（返回原文？）？Token 限制是否处理（过长文本截断）？
- [ ] `translator.py`：多提供商切换逻辑是否有 fallback 链？
- [ ] `keyword_matcher.py`：正则匹配是否有 ReDoS（正则拒绝服务）风险？等效词扩展是否有环路风险？
- [ ] `hourly_digest/selection.py`：内容选择算法是否偏向某一源？是否有最小多样性保证？
- [ ] `streaming.py`：SSE 流中断时，是否正确清理资源？客户端断开是否有处理？
- [ ] AI 成本控制：是否有内容长度上限、请求频率限制，防止意外大额账单？

**输出：** `audit/04-ai-processing.md`

---

## 模块五：API 设计与数据验证

**关键问题：**
- API 设计是否符合 RESTful 规范？错误响应是否一致？
- 输入验证是否完整（Pydantic schemas）？
- 分页、过滤、排序参数是否有注入风险？

**要读的文件：**
- `backend/app/api/sources/` — 4 个文件
- `backend/app/api/contents_crud.py`（249 行）
- `backend/app/api/content_shared.py`（271 行）— FTS 查询构建
- `backend/app/api/keywords.py`（389 行）
- `backend/app/api/digest.py`（357 行）
- `backend/app/utils/fts_query.py` — FTS5 查询构建器
- `backend/tests/test_api_keywords.py`（304 行）

**审计清单：**
- [ ] Pydantic schemas：所有 POST/PUT body 是否有严格的类型和长度限制（防止超大输入）？
- [ ] `content_shared.py`：FTS5 查询是否有 SQL 注入风险？`fts_query.py` 的转义是否完整？
- [ ] 分页参数（limit/offset）：是否有上限保护（防止 `limit=10000` 查询）？
- [ ] HTTP 方法语义：GET 是否无副作用？DELETE 是否幂等？
- [ ] 错误响应：400/401/403/404/422/500 是否一致使用？错误消息是否泄露内部信息（堆栈跟踪、SQL 错误）？
- [ ] `/api/sources/probe`：探测外部 URL 时是否经过 SSRF 检查（与采集器共用还是单独校验）？
- [ ] `/api/contents/reader`：正文加载是否有超时保护？是否限制可加载的 URL 来源（仅允许已存库的 URL）？
- [ ] Bulk 操作（批量删除等）：是否有数量上限？是否有事务保护（部分失败如何处理）？

**输出：** `audit/05-api-design.md`

---

## 模块六：数据库与并发

**关键问题：**
- SQLAlchemy async 使用是否正确（session 生命周期、连接池）？
- 并发写入是否有竞争条件？
- 数据库迁移是否安全（自动迁移在生产环境的风险）？

**要读的文件：**
- `backend/app/database.py` — 异步引擎配置
- `backend/app/models/` — 10 个模型文件（481 行）
- `backend/alembic/versions/` — 13 个迁移文件（最新 20260407_0011）
- `backend/app/services/runtime_lock_service.py`（94 行）— 分布式锁
- `backend/app/models/runtime_lock.py`（18 行）

**审计清单：**
- [ ] `database.py`：连接池大小是否合理（SQLite 不支持真正并发写，pool_size 是否为 1 或使用 WAL 模式）？
- [ ] Session 管理：是否所有数据库操作都在同一个 session 中？是否有 session 泄漏（未 close）？
- [ ] 模型设计：外键约束是否正确定义？级联删除是否符合业务逻辑？
- [ ] `runtime_lock_service.py`：锁的 TTL 是否足够覆盖最长任务？是否有锁超时自动释放？
- [ ] Alembic 迁移：迁移是否在应用启动时自动执行（`main.py` lifespan）？生产环境意外数据丢失风险是否已评估？
- [ ] Content 去重：`url` 是否有唯一索引？并发写入时是否有重复风险？
- [ ] SQLite WAL 模式：是否启用？读写并发是否有问题？
- [ ] 长事务：AI 处理和内容存储是否在同一个事务中？超长事务锁定问题？

**输出：** `audit/06-database.md`

---

## 模块七：任务调度与队列

**关键问题：**
- APScheduler 8 个定时任务是否有任务重叠保护？
- 有界任务队列是否有背压处理？
- 应用崩溃后任务是否会丢失？

**要读的文件：**
- `backend/app/scheduler.py`（100+ 行）
- `backend/app/tasks/task_queue.py`（121 行）
- `backend/app/tasks/fetch_tasks.py`（251 行）
- `backend/app/tasks/hourly_digest_tasks.py`（273 行）
- `backend/app/tasks/email_tasks.py`（400 行）
- `backend/app/tasks/maintenance_tasks.py`（109 行）
- `backend/tests/test_scheduler_jobs.py`
- `backend/tests/test_background.py`（193 行）
- `backend/tests/test_task_queue.py`

**审计清单：**
- [ ] `scheduler.py`：8 个任务是否有 `max_instances=1` 防止重叠执行？
- [ ] `fetch_tasks.py`：源到期检查逻辑是否正确处理时区（配置 Asia/Shanghai）？
- [ ] `task_queue.py`：队列满时新任务是否被丢弃？是否有告警或日志？
- [ ] `hourly_digest_tasks.py`：摘要生成失败是否会影响下一小时的触发？
- [ ] `email_tasks.py`：SMTP 连接失败是否有重试？邮件发送失败是否记录到数据库？
- [ ] `maintenance_tasks.py`：清理任务（删除旧内容）的条件是否正确？是否有误删风险？
- [ ] 崩溃恢复：重启后是否会跳过已错过的任务（APScheduler `misfire_grace_time`）？
- [ ] 任务隔离：fetch 和 process 是否共用工作线程池？能否互相阻塞？

**输出：** `audit/07-scheduler.md`

---

## 模块八：测试质量

**关键问题：**
- 测试是否真正覆盖业务逻辑，还是只测试 happy path？
- Mock 使用是否合理（是否 mock 了不该 mock 的东西）？
- 测试代码本身是否有质量问题？

**要读的文件：**
- `backend/tests/conftest.py` — fixtures 定义
- `backend/tests/test_pipeline_stages.py`（860 行）— 最大测试文件
- `backend/tests/test_website_collector.py`（955 行）— 最大测试文件
- `backend/tests/test_probe_service_security.py`（237 行）
- `coverage.xml`（覆盖率报告）
- `frontend/e2e/specs/` — E2E 测试

**审计清单：**
- [ ] 覆盖率：从 `coverage.xml` 提取各模块覆盖率，找出低覆盖区域（< 60%）。
- [ ] `conftest.py`：fixtures 是否共享状态？测试间是否互相污染（数据库 isolation）？
- [ ] Mock 合理性：是否有"mock 所有外部调用但不测真实逻辑"的反模式？关键路径是否有集成测试？
- [ ] 边界情况：空输入、超长输入、特殊字符、None 值是否有覆盖？
- [ ] 错误路径：网络超时、数据库错误、外部 API 失败是否有测试？
- [ ] E2E 测试：Playwright E2E 覆盖了哪些页面？关键流程（添加源 → 采集 → 查看内容）是否有端到端测试？
- [ ] 测试代码质量：是否有重复代码（可提取 helpers）？测试用例是否有清晰的 Arrange/Act/Assert 结构？
- [ ] `test_stage_a_fixes.py` 等 "阶段式" 测试文件：是否是临时文件，应合并进主测试文件？

**输出：** `audit/08-testing.md`

---

## 模块九：前端工程质量

**关键问题：**
- 组件是否有清晰的职责划分？
- 状态管理是否合理（React Query + Zustand 搭配）？
- API 密钥在前端的存储和传输是否安全？

**要读的文件：**
- `frontend/src/services/api.ts` — API 客户端基础
- `frontend/src/services/apiKeyStore.ts` — API 密钥存储
- `frontend/src/pages/HomePage.tsx`
- `frontend/src/pages/SettingsPage.tsx`
- `frontend/src/services/queryKeys.ts`
- `frontend/src/hooks/useDashboard.ts`
- `frontend/src/hooks/useReader.ts`
- `frontend/vite.config.ts`

**审计清单：**
- [ ] `apiKeyStore.ts`：API Key 是否明文存储在 localStorage？有无 XSS 风险（localStorage 可被 JS 访问）？
- [ ] `api.ts`：错误处理是否区分网络错误和 API 错误？是否有统一的错误边界？
- [ ] React Query：`staleTime`/`cacheTime` 配置是否合理？数据过期后是否有正确的 refetch 策略？
- [ ] 组件粒度：`SettingsPage.tsx` 是否过于庞大（GOD component）？关键配置是否有表单验证？
- [ ] Tauri 集成：`tauri.localhost` 与 `localhost:3000` 的 CSP/CORS 差异是否处理？
- [ ] 流式翻译（SSE）：useReader hook 中是否有内存泄漏（未取消的 EventSource）？
- [ ] TypeScript 严格性：是否有过多 `any`？关键类型是否与后端 Pydantic 模型一致？
- [ ] 构建产物：是否有 source map 泄露到生产环境？bundle size 是否合理？

**输出：** `audit/09-frontend.md`

---

## 模块十：CLI 与运维

**关键问题：**
- `pim` Bash 脚本是否健壮（错误处理、幂等性、跨平台）？
- `pimctl` Python CLI 是否有完整的错误提示和退出码？
- macOS LaunchAgent 安装/卸载是否安全？

**要读的文件：**
- `./pim`（1053 行）— 主启动脚本
- `cli/pimctl/app.py`（300+ 行）
- `cli/pimctl/client.py`
- `cli/pimctl/config.py`
- `.github/` — CI/CD 配置

**审计清单：**
- [ ] `pim` 脚本：是否有 `set -e`（或等效保护）？关键命令失败时是否会继续执行？
- [ ] `pim setup`：重复运行是否幂等（重复 pip install、npm install 是否安全）？
- [ ] `pim install-service`：LaunchAgent plist 是否正确设置路径（绝对路径 vs 相对路径）？重装时是否先卸载旧的？
- [ ] `pimctl`：HTTP 错误是否有清晰的用户提示（而非原始 JSON 报错）？退出码是否标准（0=成功，非0=失败）？
- [ ] `pimctl auth login`：API Key 是否安全存储（文件权限 0600）？是否明文记录在日志中？
- [ ] `pim backup`：备份文件权限是否正确？备份路径是否可配置？
- [ ] `pim logs`：是否有日志轮转？日志文件是否会无限增长？
- [ ] `.github/` CI：是否有自动化测试？是否有 lint 检查？

**输出：** `audit/10-cli-ops.md`

---

## 模块十一：依赖与工程规范

**关键问题：**
- 依赖版本是否有已知漏洞？
- `requirements.txt`（313 行）与 `pyproject.toml` 是否一致？
- 代码风格是否统一（Ruff 154 个文件异常是否合理）？

**要读的文件：**
- `backend/pyproject.toml`（161 行）
- `backend/requirements.txt`（313 行）
- `frontend/package.json`
- `.gitignore`

**审计清单：**
- [ ] 依赖安全扫描：运行 `pip-audit` 或手动检查 `requirements.txt` 中的关键包版本（Playwright、aiosqlite、FastAPI 等）。
- [ ] `pyproject.toml` vs `requirements.txt`：二者是否同步？是否有"幽灵依赖"（requirements.txt 有但 pyproject.toml 没声明的包）？
- [ ] Ruff 异常：`154 个文件例外` 是否过多？是否有规律（大量 `noqa` 注释积累的技术债）？
- [ ] 前端依赖：`package.json` 中是否有过时主版本（Ant Design 4 vs 5？React 18 最新？）？
- [ ] 代码风格一致性：是否有混用 async/sync 的地方？命名规范是否统一（snake_case vs camelCase 分界是否清晰）？
- [ ] 配置管理：是否有硬编码的 URL、端口、路径分散在代码中（而非统一从 config 读取）？

**输出：** `audit/11-deps-standards.md`

---

## 汇总输出

所有模块完成后，汇总到：

### `audit/00-summary.md`

格式：
```markdown
# PIM 代码审计报告

## 总评
[整体评价]

## 严重问题（需修复）
| # | 模块 | 问题描述 | 影响 |
|---|------|---------|------|
| 1 | 安全 | ... | 高 |

## 中等问题（建议改进）
[表格]

## 良好实践（值得保留）
[列表]

## 改进优先级路线图
1. 立即修复：...
2. 短期（1-2周）：...
3. 长期（有时间再做）：...
```

---

## 执行顺序建议

**优先级 1（并行执行）：**
- 模块二（安全）— 有问题影响最大
- 模块六（数据库并发）— 数据正确性风险
- 模块八（测试质量）— 审计基础，coverage.xml 已存在

**优先级 2（顺序执行）：**
- 模块三（采集流水线）→ 模块四（AI处理）→ 模块七（调度）
- 这三个模块是核心业务流，逻辑上连贯

**优先级 3（并行执行）：**
- 模块一（架构）— 综合前面所有模块结论
- 模块五（API设计）
- 模块九（前端）
- 模块十（CLI）
- 模块十一（依赖）

**最后：** 汇总模块（00-summary.md）
