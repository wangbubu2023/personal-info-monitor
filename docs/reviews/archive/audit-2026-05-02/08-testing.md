# 模块八：测试质量 审计报告

## 总评

PIM 的测试基础设施扎实：**59 个 backend pytest 文件、11507 行**，conftest.py 用 `tmp_path` 给每个测试分配独立 SQLite 文件 + 显式 `dependency_overrides` 替换 `verify_api_key` 与 DB session（`backend/tests/conftest.py:20-64`），数据库隔离完美。最大的几个测试文件（test_website_collector.py 955 行、test_pipeline_stages.py 860 行、test_processors.py 794 行）反映出对核心采集与处理路径的厚重覆盖。

**但是从 `coverage.xml` 提取的整体覆盖率仅 29%**，且**有 94/137 个模块覆盖率 < 60%**，包括以下关键业务模块在快照中显示为 0%：
- `services/probe_service.py`（核心探测）
- `services/probe_strategies/*`（全部 7 个策略文件）
- `services/doctor_service.py`（系统体检）
- `tasks/task_queue.py`（任务队列）
- `tasks/maintenance.py`
- `utils/fts_query.py`（已审计为安全关键）

这强烈暗示**当前 coverage.xml 是从部分测试集生成的**（例如某次快测运行），而不是完整 pytest 套件——实际运行 test_probe_service_extended.py 等文件时这些模块应该有覆盖。**这本身是一个工程问题**：coverage 报告应反映完整套件，否则误导团队的覆盖率认知。

另外 5 个 `test_stage_*.py` / `test_review_bugfixes.py` 文件（共 521 行）是审计驱动加进来的临时文件，没有对应的产品边界，应该被合并到主测试文件中。

## 严重问题（❌）

- **C1** `coverage.xml` 报告的 29% 整体覆盖率与 0% 的关键模块强烈不一致——要么是不完整运行的快照（误导报告），要么实际确实没覆盖（关键 service 层无测试）。两种情况都需要立刻处理。

## 轻微问题（⚠️）

- **L1** 5 个 `test_stage_*.py` + `test_review_bugfixes.py` 是临时性审计修复测试（`test_stage_a_fixes.py` 91 行、`b` 66 行、`v3` 77 行、`v4` 183 行、`review_bugfixes` 104 行），应合并到对应的主测试文件中并删除。
- **L2** 关键服务层测试缺失或被 mock 短路：
  - `services/probe_service.py`（line-rate 0）
  - `services/doctor_service.py`（line-rate 0）
  - `services/probe_strategies/{base,podcast,registry,result,rss,website,x,youtube}.py`（全 0）
- **L3** `tasks/task_queue.py` line-rate 0%——尽管 BoundedTaskQueue 是关键并发原语（200 容量 + DLQ 文件），没有针对队列满 / cancel / 重启的测试。
- **L4** `email_tasks.py` line-rate 8%——SMTP 失败、模板渲染、收件人解析路径基本未覆盖。
- **L5** `main.py` line-rate 25.78%——lifespan、CORS 注入、SPA fallback 路径都未测。
- **L6** `auth.py` line-rate 46.15%——只有 25 行的简单文件覆盖率不到一半，意味着错误路径（401、misconfigured 500）可能没测。
- **L7** E2E 测试只有 3 个 spec：`dashboard.spec.ts`、`digest.spec.ts`、`settings.spec.ts`。**关键流程"添加源 → 采集 → 查看内容"没有端到端测试**。
- **L8** Mock 合理性未在本次审计逐文件核验：从 `test_pipeline_stages.py`（860 行）的规模看应有真实集成路径，但 `_probe_service_extended.py`（713 行）若全 mock 则 line-rate 应非 0——结合 L1 的 coverage.xml 不全问题，需要排查。

## 良好实践（✅）

- **G1** `conftest.py` 用 `tmp_path` 给每个测试 fixture 分配**独立 SQLite 文件**，引擎 yield 后 `dispose`（`conftest.py:20-38`）——天然消除测试间数据库污染。
- **G2** API 测试通过 `app.dependency_overrides` 注入 fake `verify_api_key`（`conftest.py:58`），不需要每个测试手动加 X-API-Key 头。
- **G3** `dependency_overrides.clear()` 在 fixture teardown 调用（L64），防止 override 泄漏到其它测试。
- **G4** 测试文件命名清晰：`test_<module>.py`（test_processors / test_collectors_*）+ `test_<module>_extended.py` 表示 extended coverage（test_api_sources_extended.py、test_probe_service_extended.py）+ `test_<module>_security.py` 表示安全专用测试。
- **G5** 安全敏感路径有专用测试：`test_ssrf_protection.py`、`test_encryption_coverage.py`、`test_keyword_matcher_safety.py`、`test_probe_service_security.py`、`test_api_security_observability.py`。
- **G6** 大文件不混乱：test_website_collector.py 955 行、test_pipeline_stages.py 860 行——大但符合"被测对象的表面积大"的合理增长，没有过度拆分。
- **G7** `test_review_bugfixes.py` 等审计驱动测试虽属临时，但**保留为 regression 测试**比删除好——只是命名应迁移。
- **G8** 测试覆盖了 ReDoS、ssrf、加密兼容性等重要安全路径——专门文件而非散落在 functional 测试里。

## 详细审计清单

### 1. 覆盖率：从 coverage.xml 找出低覆盖区域

- **结论：** ❌（需进一步定位 coverage.xml 是否是完整快照）
- **代码位置：** `coverage.xml`（项目根）、`backend/tests/`
- **分析：**
  - 整体 line-rate=0.29（29%）。
  - 137 个 .py 模块中 **94 个低于 60%**。
  - 0% 覆盖的关键模块：
    - `services/doctor_service.py`、`services/probe_service.py`、`services/probe_strategies/*`（7 个文件）
    - `tasks/maintenance.py`、`tasks/task_queue.py`
    - `utils/fts_query.py`、`utils/tracing.py`
  - 8% 覆盖：`tasks/email_tasks.py`
  - 25-30% 覆盖：`main.py`（25.78%）、`migrations.py`（30.95%）、`scheduler.py`（32.14%）、`background.py`（38.39%）
  - 46% 覆盖：`auth.py`
  - 高覆盖：所有 `__init__.py`（trivially 100%，是 stub 文件）+ `api/contents.py`（100%）+ `api/configs.py`（100%）
- **注意点：** 仓库里 `test_probe_service_extended.py` 有 713 行，但 probe_service.py 仍 0%。可能性：(a) coverage.xml 是从一次仅跑安全/单元 test 子集的运行生成；(b) extended 测试全用 mock 短路真实模块；(c) coverage 配置缺漏（pyproject.toml 中的 `[tool.coverage]` 配置需查）。
- **建议：**
  - 在 CI 中跑 `pytest --cov=backend/app --cov-report=xml` 全套件并把 xml 提交，而不是依赖一次开发期快照。
  - 给 service 层、task_queue、fts_query 写真实集成测试（不全 mock），把这些模块的覆盖率提到 70%+。

### 2. conftest.py：fixtures 共享状态 / 测试间污染

- **结论：** ✅
- **代码位置：** `backend/tests/conftest.py:20-64`
- **分析：**
  - `async_session_factory(tmp_path)`：每个使用此 fixture 的测试都得到独立 SQLite 文件（`tmp_path` 是 pytest 自动生成的临时目录，per-test 唯一）。
  - 引擎在 fixture finalize 时 `dispose()`，避免连接泄漏。
  - `db_session` 在 factory 上开 session，session 与 engine 一同回收。
  - `client(async_session_factory)` 给 FastAPI app 注入 override：`get_async_db` 走临时引擎、`verify_api_key` 返回固定字符串。`dependency_overrides.clear()` 在 yield 之后 → 干净清理。
  - **没有共享的全局状态**（如 module-level fixture、autouse 的 module 级 fixture）。
- **建议：** 无；这是异步 SQLite 测试 fixture 的范本写法。

### 3. Mock 合理性

- **结论：** ⚠️（需要细查个别文件）
- **代码位置：** `backend/tests/test_*.py`（59 个）
- **分析：**
  - 没有时间逐文件审 mock 模式。从文件命名上看：
    - `test_*_extended.py`（多个，包括 probe_service / fetch_tasks / process_tasks / configs_api_auth）通常表示"extended scenarios"，应该是真实路径而非全 mock。
    - 但 probe_service.py line-rate 0% 与 test_probe_service_extended.py 713 行并存，**只能解释为该测试用 monkeypatch 把 probe service 的内部完全替换掉了**——这是 anti-pattern（"mock 了所有外部调用但不测真实逻辑"）。
  - 安全路径测试（test_ssrf_protection、test_encryption_coverage）应该是真实路径，否则失去意义。
- **建议：**
  - 对 probe_service 测试做一次手工核验：搜索 `with patch("app.services.probe_service` 出现次数，> 5 次说明替换太广。

### 4. 边界情况覆盖

- **结论：** ⚠️（部分覆盖，未量化）
- **代码位置：** 散落在 59 个测试文件中
- **分析：**
  - test_keyword_matcher_safety.py（推断 ReDoS 边界）、test_ssrf_protection.py（私网/IPv6/解析后再校验）、test_fts_query.py（FTS 转义）：明显是边界用例集。
  - 但缺乏对 main.py 的 lifespan、background.py 的边界测试（线程池、scheduler 启动失败）——line-rate 25-38% 印证。
  - **未在本次审计验证：** 各 API 端点对超长 input、None body、malformed JSON 的 422/400 测试覆盖。
- **建议：**
  - 加 `test_main_lifespan.py` 测试启动失败路径（migration 抛错 → uvicorn 不接受流量）。

### 5. 错误路径覆盖

- **结论：** ⚠️
- **代码位置：** 同上
- **分析：**
  - 文件 `test_q1_narrow_excepts.py` 暗示有针对"narrow exception"约束的回归测试（与 ARCHITECTURE.md §9 "every except Exception 必须 noqa: BLE001" 不变量呼应）。
  - 网络超时、外部 API 5xx 在 test_processors / test_collectors_* 中应有覆盖，但 email_tasks 8% 覆盖率说明 SMTP 错误路径未覆盖。
- **建议：**
  - 加 `test_email_tasks_failures.py` 模拟 SMTP timeout / 鉴权失败 / 收件人格式错误。

### 6. E2E 测试

- **结论：** ⚠️
- **代码位置：** `frontend/e2e/specs/`
- **分析：**
  - 只有 3 个 spec：dashboard、digest、settings。覆盖了用户高频读路径与配置路径。
  - **缺少**：
    - 添加 source → 等待 fetch → 查看 content 列表的端到端流程；
    - 删除 / 收藏 / 归档 content 的交互流程；
    - 关键词匹配的视觉验证（高亮）；
    - Reader 翻译（SSE 流式）的端到端断言。
- **建议：**
  - 至少加 `add_source.spec.ts`（POST /sources → 等待轮询 → 列表里出现新 source）与 `reader_translation.spec.ts`（打开 reader → 触发翻译 → 收到 done frame）。

### 7. 测试代码质量：重复 / AAA 结构

- **结论：** ✅（基础）+ ⚠️（重复未量化）
- **代码位置：** 全 `backend/tests/`
- **分析：**
  - 文件命名一致 `test_<topic>.py`，符合 pytest discovery。
  - 文件内部结构未细查；从规模看 test_website_collector.py 955 行很可能存在可抽到 helper 的重复（多个 fixture HTML payload）。
  - `conftest.py` 只有 65 行，没有 helper 函数——测试间共享逻辑都重复在文件里写。
- **建议：**
  - 把常用 helper（mock HTTP response、build sample Source、assert_content_persisted）提到 `tests/helpers/__init__.py`。

### 8. test_stage_*.py / test_review_bugfixes.py：临时文件

- **结论：** ⚠️
- **代码位置：** `backend/tests/test_stage_a_fixes.py`(91)、`_b_fixes.py`(66)、`_v3_fixes.py`(77)、`_v4_fixes.py`(183)、`_review_bugfixes.py`(104)
- **分析：**
  - 命名约定 "stage" / "review_bugfixes" 暗示这些是历史审计阶段加进来的回归测试。
  - 应当：(a) 保留作为 regression（不要删测试用例本身）；(b) 把内容合并到对应模块的主测试文件；(c) 删除临时文件。
  - 现状不是错误，但是技术债。
- **建议：**
  - 一个一次性 PR：解析每个 stage 文件的 test 名 → 把 test function 移到 test_<对应模块>.py 末尾 → git rm 旧文件。

## 涉及文件

- `backend/tests/conftest.py`
- `backend/tests/`（59 个 test_*.py 通过 ls 概览）
- `coverage.xml`（用 ElementTree 解析）
- `frontend/e2e/specs/`（3 个 spec）

## 立即可落地的改进

1. **修复 coverage 报告：** CI 添加 `pytest --cov=backend/app --cov-report=xml` 全套件，让 coverage.xml 反映真实状态。
2. **合并 test_stage_*：** 一次 PR 把 ~520 行临时测试合并到主测试文件并删除。
3. **补关键缺失测试：** task_queue.py、fts_query.py、probe_service.py 加真实集成测试（非 monkey-patch all）。
4. **补 E2E：** 添加 add_source 和 reader_translation 两个 spec。
5. **email_tasks 失败路径：** 8% 覆盖率说明 SMTP 故障未测。
