# 项目结构说明（每个文件/文件夹的作用）

> 适用版本：master 当前 HEAD（post-Phase-7 audit 之后），后端约 270 个
> Python 模块、约 80 个测试文件；前端约 100 个 TS/TSX 文件；CLI 7 个模块；
> 文档 16 篇活档 + reviews 归档。具体数量随重构变动，以仓库实际为准
> （例如 `find backend/app -name '*.py' | wc -l`）。
>
> 配套阅读：[`ARCHITECTURE.md`](./ARCHITECTURE.md)（架构总览）、
> [`MODULE_BOUNDARIES.md`](./MODULE_BOUNDARIES.md)（边界一页纸）。
> 重构实施历史见 [`reviews/archive/MODULE_REFACTOR_PLAN.md`](./reviews/archive/MODULE_REFACTOR_PLAN.md)。

---

## 目录

1. [仓库根](#1-仓库根)
2. [`backend/` 后端](#2-backend-后端)
   - 2.1 [后端根文件](#21-后端根文件)
   - 2.2 [`backend/alembic/` 数据库迁移](#22-backendalembic-数据库迁移)
   - 2.3 [`backend/scripts/` 一次性运维脚本](#23-backendscripts-一次性运维脚本)
   - 2.4 [`backend/tests/` 后端测试](#24-backendtests-后端测试)
   - 2.5 [`backend/app/` 核心源码](#25-backendapp-核心源码)
     - 顶层入口
     - `interfaces/`
     - `domains/`
     - `platform/`
     - `models/` / `schemas/`
     - 历史 shim 目录
3. [`frontend/` 前端](#3-frontend-前端)
4. [`cli/pimctl/` CLI 包](#4-clipimctl-cli-包)
5. [`docs/` 文档](#5-docs-文档)
6. [`.github/` CI](#6-github-ci)

---

## 1. 仓库根

```
personal-info-monitor/
├── README.md            项目门面：架构一句话 / 启动 / 配置 / 文档地图
├── LICENSE              MIT 许可
├── .gitignore           忽略 venv / node_modules / target / 各类构件
├── pim                  macOS lifecycle 脚本（setup / start / install-service /
│                        status / logs / backup / rollback / cleanup / bootstrap-url）
│                        ↳ 只依赖系统 Python 3.11+ 与 backend/venv，单文件 Python 脚本
├── pimctl               极薄 shell wrapper，转发到 cli/pimctl/__main__.py
├── backend/             后端 Python 服务（详见 §2）
├── frontend/            前端 React + Tauri（详见 §3）
├── cli/                 pimctl CLI 包（详见 §4）
├── docs/                所有 Markdown 文档（详见 §5）
└── .github/             GitHub Actions CI 工作流（详见 §6）
```

`./pim` 和 `./pimctl` 角色严格分开：

- **`./pim`** = 宿主机运维。venv / 服务注册 / 启停 / 备份 / 日志轮转。
  本地或 VPS 都用，不通过 HTTP 调用，直接管理本机进程。
- **`./pimctl`** = 业务调用。每条命令都封装一条或几条 API 请求，统一
  支持 `--json` 信封，专为 Agent / 自动化设计。

---

## 2. `backend/` 后端

### 2.1 后端根文件

```
backend/
├── README.md              后端目录树 + 启动 / 测试 / lint 速查（详见 §2.5）
├── .env.example           运行所需环境变量样例（手动复制为 .env）
├── pyproject.toml         唯一手工维护的依赖清单 + ruff 配置 +
│                          pytest 配置 + BLE001 per-file-ignores baseline
├── uv.lock                uv lock 产物，提交到仓库（依赖锁定的事实源）
├── requirements.txt       由 `uv export --no-hashes --no-dev` 自动导出，
│                          供 ./pim setup 与 CI 使用
├── requirements-dev.txt   含 pytest/ruff 的开发依赖快照
├── alembic.ini            Alembic 配置（指向 backend/alembic）
├── alembic/               迁移脚本（详见 §2.2）
├── scripts/               一次性运维脚本（详见 §2.3）
├── tests/                 后端 pytest 测试（详见 §2.4）
└── app/                   核心源码（详见 §2.5）
```

### 2.2 `backend/alembic/` 数据库迁移

```
alembic/
├── env.py                 Alembic 环境引导：连接 SQLite、加载 ORM metadata
├── script.py.mako         migration 模板
└── versions/              迁移文件（按时间戳排序）
    ├── 20260330_0001_initial_schema.py                  初始 schema
    ├── 20260331_0002_review_fixes.py                    第三版审计修复
    ├── 20260331_0003_auth_config_labels.py              auth_config 加标签字段
    ├── 20260401_0004_content_publish_fetched_indexes.py 加 published/fetched 索引
    ├── 20260401_0005_source_use_keyword_filter.py       Source 加关键词过滤开关
    ├── 20260407_0006_keyword_scope_equivalents.py       Keyword 等价术语
    ├── 20260407_0007_normalize_keyword_enum_values.py
    ├── 20260407_0008_remove_source_categories_priority.py
    ├── 20260407_0009_keyword_manual_equivalent_intervention.py
    ├── 20260407_0010_keyword_notify_default_off.py      关键词默认不推送
    ├── 20260407_0011_keyword_identity_unique.py
    ├── 20260503_0012_content_original_url_index.py
    ├── 20260520_0013_create_content_atom_bundles.py     Phase 6 atoms 表
    ├── c36115ec5636_add_fts5_search_table.py            FTS5 全文搜索虚表
    └── effcf9c68468_add_content_is_user_edited.py       Content.is_user_edited 字段
```

应用启动会在 `app.platform.runtime.lifespan` 中自动跑 `alembic upgrade head`；
手动也可 `cd backend && alembic upgrade head`。

### 2.3 `backend/scripts/` 一次性运维脚本

```
scripts/
├── analyze_weekly_crawls.py     分析每周抓取行为的诊断脚本
├── cleanup_inactive_sources.py  清理长期不活跃的信源（手动巡检用）
└── check_domain_imports.py      静态 AST 检查器，按 --phase=N 校验导入边界
                                 是 CI 的核心质量门，违反任一规则会让 PR fail
```

`check_domain_imports.py` 是模块化重构的「围栏」：把
`platform → domains`、`domains → interfaces`、引用已删除 shim 等违规
import 在合并前阻断。

### 2.4 `backend/tests/` 后端测试

约 80 个测试文件（逾千个用例，具体数量以 `pytest` 实跑为准），覆盖 atoms / collectors / API / pipeline /
auth / FTS / keyword / metrics / probe / ssrf / browser / hourly digest 等。

按主题分组（部分代表性文件）：

| 主题 | 文件 |
|---|---|
| 端到端 API | `test_api_sources*.py`、`test_api_contents.py`、`test_api_digest.py`、`test_api_keywords.py`、`test_api_auth_configs.py`、`test_api_security_observability.py` |
| 抓取 / collectors | `test_website_collector.py`、`test_website_parser.py`、`test_collectors_base.py`、`test_collectors_rss_youtube.py`、`test_x_graphql.py`、`test_x_twitter_text.py`、`test_fetch_orchestrator.py`、`test_fetch_tasks_extended.py` |
| Ingest / pipeline | `test_pipeline_stages.py`、`test_process_tasks_extended.py`、`test_content_quality_filters.py`、`test_content_quality_scoring.py`、`test_url_dedupe.py`、`test_keyword_*.py` |
| Enrich | `test_processors.py`、`test_reader_split.py`、`test_contents_reader.py`、`test_hourly_digest_*.py`、`test_email_tasks.py` |
| Atoms | `test_atoms_api.py`、`test_atoms_extractor.py`、`test_atoms_repository.py`、`test_atoms_types.py`、`test_atoms_vocab.py`、`test_atoms_relations.py` |
| 平台层 | `test_encryption_coverage.py`、`test_ssrf_protection.py`、`test_metrics_*.py`、`test_logger_job_id.py`、`test_task_queue.py`、`test_scheduler_jobs.py`、`test_background.py`、`test_browser_playwright_prefs.py`、`test_cookie_utils.py` |
| 调度 / 边界 | `test_sources_scheduling.py`、`test_source_limits.py`、`test_system_settings_limits.py` |
| 配置 / 浏览器 | `test_configs_browser.py`、`test_configs_common_browser.py`、`test_configs_api_auth_extended.py` |
| 工具 / utils | `test_publish_time.py`、`test_human_timing.py`、`test_http_utils.py`、`test_fts_query.py`、`test_fts_api.py`、`test_text_binary.py` |
| 阶段性回归 | `test_phase1_decoupling.py`（Phase 1 解耦守门）、`test_review_bugfixes.py`、`test_stage_{a,b,v3,v4}_fixes.py`、`test_q1_narrow_excepts.py` |
| 公共 fixture | `conftest.py`（DB / env / settings cache 全套自动化） |

### 2.5 `backend/app/` 核心源码

**232 个 Python 模块，分为四类目录**（蓝图 Phase 0–7 落定）：

1. **顶层入口与基础设施薄 shim**（`app/*.py`）
2. **交付层** `interfaces/`（外向适配器）
3. **领域层** `domains/`（业务）
4. **平台层** `platform/`（横切基础设施）
5. **共享层** `models/` / `schemas/`
6. **历史 shim** `collectors/` / `processors/` / `services/` / `tasks/` /
   `pipeline/` / `utils/` / `middleware/` / `ai/` / `data/` / `api/`
   （仍被测试或运行时引用，不能轻易删）

#### 2.5.1 顶层入口（`backend/app/*.py`）

```
app/__init__.py          标识 app 为 Python 包
app/main.py              FastAPI 应用工厂：CORS / 中间件 / 路由挂载 / lifespan
                          → uvicorn app.main:app 的入口
app/scheduler.py         APScheduler 作业注册（fetch / digest / cleanup / email）
app/background.py        Phase 2 之后的薄 shim：转发到 platform.locks 与
                          platform.runtime；保留是为兼容老测试 patch target
app/features.py          运行时功能开关（PODCAST_SOURCES_ENABLED /
                          KEYWORD_MONITORING_ENABLED / ATOMS_ENABLED 等）
app/config.py            shim → app.platform.config.settings.get_settings
app/database.py          shim → app.platform.persistence.database 的
                          SessionLocal / AsyncSessionLocal / get_db / get_async_db
app/auth.py              shim → app.platform.auth.api_key 的 verify_api_key
app/migrations.py        启动时调 Alembic upgrade 的薄封装
```

> 这 9 个文件中除 `main.py` / `scheduler.py` 外，大部分已退化为薄 shim，
> 新代码请直接走 canonical 路径。

#### 2.5.2 `interfaces/http/` 交付层（HTTP 路由）

```
interfaces/
└── http/
    ├── __init__.py                把全部子路由组装成 api_router
    ├── system.py                  /api/system/*（健康、指标、自检）
    ├── dashboard.py               /api/dashboard/* 首页聚合
    ├── digest.py                  /api/digest/* 日报 + 3 小时报
    ├── keywords.py                /api/keywords/* 关键词管理
    ├── content_shared.py          paragraph split / 标题清洗 / X URL 抽取等
    │                              路由层与 reader 共享的纯函数集合
    ├── contents.py                /api/contents 列表 / 搜索
    ├── contents_crud.py           /api/contents/{id} GET/PATCH/DELETE/导出 MD
    ├── contents_reader.py         /api/contents/{id}/reader 正文 + 流式翻译
    ├── contents_cleanup.py        /api/contents/cleanup 低质量清扫
    ├── configs.py                 /api/configs/* 顶层路由聚合
    ├── configs_api_auth.py        API key / cookies / 凭据相关
    ├── configs_browser.py         浏览器登录 / storage-state
    ├── configs_system.py          系统设置（限额 / Prompt / 模型）
    ├── configs_common_auth.py     auth/cookie 凭据公共逻辑
    ├── configs_common_browser.py  浏览器输入校验 / 错误归类
    ├── configs_common_cookies.py  cookie 解码 / 校验
    └── sources/                   /api/sources/* 拆 4 个子路由
        ├── __init__.py            聚合：query / mutation / probe / fetch_import
        ├── _helpers.py            quota / cache 失效 / 探测 URL 等共用
        ├── query.py               GET / search / export
        ├── mutation.py            POST / PATCH / DELETE
        ├── probe.py               /probe + /probe-all + /{id}/probe
        └── fetch_import.py        /bulk-import + /fetch-all + /{id}/fetch
```

> 这一层只做"请求→DTO→调用 domains→响应"的薄路由，不放业务逻辑、
> 不写 ORM 查询之外的 SQL。

#### 2.5.3 `domains/` 领域层（五个领域）

**核心契约层（跨领域 DTO）：**

```
domains/contracts/
├── __init__.py
├── atoms.py        AtomBundle / AtomReader Protocol
├── enrich.py       EnrichRequest / Result
├── fetch.py        FetchBatch（抓取产物 schema）
├── ingest.py       IngestResult / NormalizedContent
└── sources.py      SourceSnapshot / SourceScheduleHint
```

**1. `domains/sources/` 信源**

```
sources/
├── __init__.py             领域 docstring + 公共导出
├── source_types.py         信源类型枚举与展示名（旧 app/data/source_types.py 已删）
├── scheduling.py           effective_due_interval_minutes 等调度规则；
│                           取代旧 monitor_service / fetch_tasks 内联逻辑
├── status.py               信源状态机（healthy / degraded / inactive）
└── probe/                  probe 策略目前仍住在 services/probe_strategies/
    └── __init__.py         （此目录是未来 probe 整包迁入的占位）
```

**2. `domains/fetch/` 抓取**

```
fetch/
├── __init__.py
├── orchestrator.py         fetch_source_async 入口：拿 collector、读 schedule、
│                           调 retry、回写状态。tasks/fetch_tasks 调它
├── collectors/             所有 collector 的 canonical home
│   ├── __init__.py         get_collector(source_type) 工厂
│   ├── base.py             BaseCollector 抽象 + 共享 helpers
│   ├── rss.py              RSSCollector：feedparser + RSSHub 回退
│   ├── website.py          WebsiteCollector：fetch / hydrate 状态机
│   ├── website_helpers.py  URL/Cookie 判定（纯函数）
│   ├── website_parser.py   HTML 解析（trafilatura + 直接 fixture 可测）
│   ├── youtube.py          YouTubeCollector（yt-dlp）
│   ├── podcast.py          PodcastCollector（feedparser，audio enclosure）
│   ├── x_twitter.py        XCollector：graphql → rsshub → nitter → api 多策略回退
│   ├── x_twitter_text.py   纯文本/URL 工具
│   └── x_twitter_formatters.py  X 数据格式化
└── auth/                   抓取所需的 cookies / 凭据 / 浏览器登录
    ├── __init__.py
    ├── browser.py          Playwright 登录捕获、storage_state 保存
    ├── credentials.py      API key / token 解密载入
    ├── refresh.py          凭据自动刷新
    └── warnings.py         过期 / 失效凭据的告警归类
```

**3. `domains/ingest/` 归并入库**

```
ingest/
├── __init__.py
├── build_content.py        FetchBatch → 原始 Content ORM 对象数组
├── normalizer.py           URL / 标题 / 时区 / 时间字段规范化
├── dedupe.py               按 URL+title+content_hash 去重
├── extractor.py            正文抽取 wrapper（trafilatura / readability）
├── quality.py              质量过滤：垃圾内容 / 重复 / 过短
├── quality_metadata.py     给 Content 打质量元信息（origin_quality / signal_score）
├── keywords/
│   ├── __init__.py
│   ├── matcher.py          KeywordMatcher：编译关键词规则 → 匹配 Content
│   └── rules.py            规则解析与等价术语展开
├── scoring.py              排序信号（recency / source weight / quality）
├── search.py               FTS5 索引写入
├── storage.py              批量 upsert + on_conflict 策略
├── cleanup.py              过期 / 低质内容清理
└── finish.py               ingest → enrich → atoms → notify 的唯一汇合点
                            ★ 整个抓取流水线的最终点
```

**4. `domains/enrich/` LLM 富化 + Reader + Digest + 通知**

```
enrich/
├── __init__.py             领域 docstring（Phase 4 全部子模块说明）
├── content/                摘要 / 翻译触发与人工再处理
│   ├── __init__.py
│   └── reprocess.py        ContentProcessor.reprocess_content 的实际实现
├── reader/                 正文加载 / 翻译 / NDJSON 流（旧 services/reader/）
│   ├── __init__.py
│   ├── shared.py           paragraph split / X clean / 标题启发 / 翻译有效性门
│   ├── body_loader.py      Reader body 抓取 + X 全文升级 + cookie 加载
│   ├── translation.py      翻译协调（标题 + 正文）+ 翻译缓存
│   └── streaming.py        NDJSON 帧渲染（/contents/{id}/reader stream）
├── hourly/                 3 小时报（旧 services/hourly_digest/）
│   ├── __init__.py
│   ├── text_utils.py       category / 限额 / 提示词模板的纯函数
│   ├── selection.py        LLM 候选选择 + 本地排名回退
│   ├── synthesis.py        LLM 合成 + 规则回退渲染
│   ├── repository.py       DB 读写 + 窗口计算
│   └── tasks.py            orchestrator：load → pick → synth → store
└── notifications/          邮件触发的域内模板（旧 app/tasks/email_tasks.py）
    ├── __init__.py
    ├── daily_digest.py     日报 HTML 渲染 + 发送
    ├── doctor_digest.py    DoctorService 异常告警邮件
    └── keyword_alert.py    关键词命中通知
                            ↳ 这三个调用 platform.notifications.smtp 发信
```

**5. `domains/atoms/` 可选结构化原子事件层（Phase 6）**

```
atoms/
├── __init__.py            领域 docstring + 公共导出
├── schema.py              CURRENT_SCHEMA_VERSION / SUPPORTED_SCHEMA_VERSIONS
│                          atom_bundle_from_row（ORM → AtomBundle DTO）
├── atomizer.py            atomize_content(content_id)：idempotent + 异常吞尽
│                          的 best-effort 写入；由 finish_content 旁路调用
└── repository.py          SqlAtomReader：AtomReader 协议的 SQL 实现
                           enrich 通过协议消费，永远不直接 import 此模块
```

> 由 `ATOMS_ENABLED` 开关控制，默认关闭；开启后也只是 finish_content 的
> 旁路 best-effort 写入，永远不阻塞 ingest 主链。

#### 2.5.4 `platform/` 平台层（横切基础设施）

**13 个子包**，禁止依赖任何 `domains.*`，被所有上层共享：

```
platform/
├── __init__.py
├── auth/                       认证 / 凭据 / cookies
│   ├── api_key.py              X-API-Key 校验 + 兼容头
│   ├── bootstrap_token.py      ./pim bootstrap-url 一次性令牌
│   ├── api_credentials.py      OpenAI / RSSHub / X 等 API 凭据加解密
│   ├── credentials.py          通用凭据存取
│   └── cookies.py              cookies 加密存储与读取
├── config/                     配置 + DB 用户设置
│   ├── settings.py             Pydantic Settings：环境变量 → 全局对象
│   ├── system_settings.py      DB 表 system_settings 的 cached accessor
│   └── __init__.py
├── persistence/                数据库
│   ├── database.py             create_engine / Session / async session
│   └── __init__.py
├── workers/                    后端任务队列
│   ├── queue.py                有界 asyncio.Queue（fetch / process 双队列）
│   └── __init__.py
├── observability/              日志 / 指标 / 追踪
│   ├── logger.py               JSON / 人类双格式 + request id / job id 绑定
│   ├── metrics.py              Prometheus 计数器 / 直方图 + 持久化 checkpoint
│   ├── tracing.py              span id 生成 + with_span 上下文
│   └── __init__.py
├── security/                   加密 + SSRF
│   ├── encryption.py           Fernet 对称加密（凭据封装）
│   ├── ssrf.py                 outbound SSRF 守门
│   └── __init__.py
├── browser/                    Playwright 池 / stealth / hosts 设置
│   ├── pool.py                 共享 chromium 生命周期
│   ├── bootstrap.py            初次安装 / 升级 chromium
│   ├── playwright_runtime.py   运行时配置
│   ├── playwright_stealth.py   反指纹 patch
│   ├── hosts.py                host 白名单
│   ├── login_capture.py        登录捕获器（用于 fetch.auth.browser）
│   ├── profiles.py             浏览器 profile 管理
│   ├── session_runtime.py      Session 复用
│   ├── validation.py           cookies / storage-state 合法性检查
│   └── __init__.py
├── llm/                        LLM provider 代理
│   ├── summarizer.py           Summarizer + enrich_summary_enabled 门控
│   ├── translator.py           Translator + enrich_translate_enabled 门控
│   └── __init__.py
├── notifications/              SMTP 出站传输
│   ├── smtp.py                 send_email() + aiosmtplib 封装
│   └── __init__.py
├── export/                     导出器
│   ├── markdown.py             MarkdownExporter（YAML frontmatter + body）
│   └── __init__.py
├── locks/                      运行时锁
│   ├── runtime_lock.py         数据库表 runtime_lock + 进程级回退
│   └── __init__.py
├── runtime/                    生命周期钩子
│   ├── lifespan.py             FastAPI lifespan：Alembic / scheduler / queue 启停 / metrics restore
│   └── __init__.py
└── health/                     探针端点（被 main.py 挂在 / 根）
    ├── router.py               /livez 与 /health 两个端点
    └── __init__.py
```

#### 2.5.5 共享层

**`models/`** — SQLAlchemy ORM 实体（11 个表）

```
models/
├── __init__.py                    暴露所有 ORM 类
├── source.py                      Source 信源
├── content.py                     Content 主表（+ FTS5 虚表）
├── keyword.py                     Keyword 关键词
├── auth_config.py                 信源认证配置
├── browser_session.py             浏览器登录态
├── email_schedule.py              邮件订阅
├── hourly_digest.py               小时简报
├── runtime_lock.py                runtime_lock 锁表
├── system_setting.py              system_settings 配置表
└── atom.py                        ContentAtomBundle（Phase 6 atoms 表）
```

**`schemas/`** — Pydantic 请求/响应 DTO

```
schemas/
├── __init__.py
├── source.py
├── content.py
├── digest.py
├── keyword.py
└── config.py
```

#### 2.5.6 历史 shim 目录（仍保留是因为有真实 patch target 或运行时 caller）

```
api/__init__.py                  Phase 5 引入的 sys.modules 别名脚本：
                                 把 app.api.X 解析到 app.interfaces.http.X，
                                 让 app/main.py 的 `from app.api import api_router`
                                 与所有测试 `patch("app.api.contents.X")` 保持工作
collectors/                      shim → domains.fetch.collectors（7 个文件保留：
  base.py, rss.py, website.py,   每个都是测试或运行时仍用的 patch target；
  website_parser.py, x_twitter.  Phase 7 audit 已删 podcast/website_helpers/
  py, x_twitter_text.py,         x_twitter_formatters 三个无 caller 的）
  youtube.py
processors/                      shim → platform.llm + domains.ingest.extractor
  content_processor.py           仍是 enrich 入口（reprocess / summarize / translate
                                 的 orchestrator），其余 4 个是 shim
  extractor.py / keyword_matcher.py / summarizer.py / translator.py
services/                        历史"服务层"，已重组但保留下列活模块：
  api_config_credentials.py      凭据保护服务（HTTP 层调用）
  content_quality_service.py     调用 domains.ingest.quality
  digest_service.py              日报 CRUD 服务（routes 调用）
  doctor_service.py              系统自检 + 告警判定
  keyword_rules.py               关键词规则缓存（routes 调用）
  monitor_service.py             调用 domains.sources.scheduling
  probe_service.py               + probe_strategies/  探测服务（HTTP /probe）
  ranking_service.py             排序服务（dashboard 调用）
  scoring_service.py             打分服务（dashboard 调用）
  probe_strategies/
    base.py                      ProbeStrategy Protocol（契约）
    registry.py                  策略注册表 {source_type → Strategy}
    result.py                    ProbeResult dataclass
    rss.py / website.py / x.py / youtube.py / podcast.py
                                 5 个策略实现（结构化探测）
tasks/                           调度入口 + 几个仍直接被 scheduler 调用的任务
  fetch_tasks.py                 fetch_source / fetch_all_due / fetch_one
  fetch_auth_helpers.py          抓取前的凭据获取助手
  process_tasks.py               异步处理入口：调 domains/ingest 与 enrich
  task_queue.py                  shim → platform.workers.queue
  maintenance.py                 维护 job（清理、归档）
  maintenance_tasks.py           markdown 导出、备份、清理等定时
pipeline/                        历史"流水线协调器"，coordinator 仍是 fetch 主链
  coordinator.py                 run_fetch_pipeline：从 source 到 finish_content
  collector_stage.py             collector 阶段封装
  normalizer_stage.py            normalize 阶段封装
  storage_stage.py               storage 阶段封装
  dedupe.py / utils.py           工具
                                 ↑ 这一层会在未来 Phase 8+ 进一步拆并；
                                 当前用作 fetch + ingest 之间的胶水
utils/                           保留下列活的小工具：
  browser.py                     shim → platform.browser.pool
  cookies.py                     cookies 解码工具（独立于 platform）
  datetime.py                    utcnow_naive 等时间统一
  encryption.py                  shim → platform.security.encryption（patch target）
  fts_query.py                   FTS5 查询语法构建
  http.py                        httpx wrapper（共享 timeout / retry）
  human_timing.py                "3 小时前"等相对时间
  logger.py                      shim → platform.observability.logger（patch target）
  metrics.py                     shim → platform.observability.metrics（patch target）
  model_catalog.py               读取 data/model_providers.json
  playwright_runtime.py          shim → platform.browser.playwright_runtime
  playwright_stealth.py          shim → platform.browser.playwright_stealth
  publish_time.py                publish_time 解析（多种格式）
  text.py                        文本归一 / 清洗
  ttl_cache.py                   asyncio TTLCache
  url.py                         URL canonicalize / hash / 等价类
middleware/                      只剩 1 个活的中间件
  api_rate_limit.py              基于 sliding-window 的限速
ai/                              ai/provider.py：通用 OpenAI-compatible client
                                 （摘要 / 翻译 / 简报都通过它）
data/                            静态资源（不是 Python module）
  model_providers.json           模型 provider 元数据（OpenAI/Anthropic/DeepSeek/...）
```

> 历史 shim 的核心判断标准：**有真实 caller 或 `patch()` target**。
> Phase 7 + post-Phase-7 audit 已经把所有「无 caller / 无 patch target」
> 的 shim 删除，剩下这些都是有理由保留的。

---

## 3. `frontend/` 前端

```
frontend/
├── README.md              前端目录树 + 启动 / 测试 / 构建说明
├── package.json           npm 依赖与脚本（dev / build / preview / test）
├── package-lock.json      npm lock
├── tsconfig.json / tsconfig.node.json   TypeScript 配置
├── vite.config.ts         Vite 配置（含 /api → backend 代理）
├── vitest.config.ts       Vitest 单元测试
├── playwright.config.ts   Playwright E2E 配置
├── postcss.config.js      Tailwind 后处理
├── tailwind.config.js     Tailwind 主题
├── .eslintrc.cjs          ESLint
├── index.html             Vite 入口
├── src/                   React 源码（见下）
├── e2e/                   Playwright E2E
│   ├── fixtures/
│   │   └── apiMocks.ts    后端响应桩
│   └── specs/
│       ├── dashboard.spec.ts
│       ├── digest.spec.ts
│       └── settings.spec.ts
└── src-tauri/             Tauri 桌面壳
    ├── Cargo.toml         Rust 依赖
    ├── Cargo.lock         Rust lock
    ├── tauri.conf.json    Tauri 应用配置（窗口 / icon / 权限）
    ├── build.rs           Tauri build script
    ├── .gitignore         排除 target/
    ├── src/
    │   ├── main.rs        桌面入口
    │   └── lib.rs         Tauri 命令导出
    ├── capabilities/
    │   └── default.json   Tauri permission capabilities
    ├── icons/
    │   └── icon.png       应用图标
    └── gen/schemas/       Tauri build 时自动生成的 JSON schema
        ├── acl-manifests.json
        ├── capabilities.json
        ├── desktop-schema.json
        └── macOS-schema.json
```

### `frontend/src/`

```
src/
├── App.tsx                顶层路由 + 全局 Provider 注入
├── main.tsx               ReactDOM 入口
├── components/            UI 组件（按页面分组，见下）
├── pages/                 路由页面
│   ├── HomePage.tsx
│   ├── DigestPage.tsx
│   ├── ReaderPage.tsx
│   ├── SettingsPage.tsx
│   └── SourcesPage.tsx
├── hooks/                 共享 hooks
│   ├── useDashboard.ts    首页数据 + 队列状态轮询
│   └── useReader.ts       Reader 抓取 + 流式翻译
├── services/              后端 API 调用层
│   ├── api.ts             封装 axios + X-API-Key 自动注入
│   ├── apiKeyStore.ts     LocalStorage 中 API Key 的存取
│   ├── sources.ts         /api/sources/*
│   ├── contents.ts        /api/contents/*
│   ├── digest.ts          /api/digest/*
│   ├── keywords.ts        /api/keywords/*
│   ├── configs.ts         /api/configs/*
│   ├── browserSessions.ts /api/configs/browser/* 浏览器登录态
│   ├── system.ts          /api/system/*
│   ├── queryKeys.ts       React Query 的 key 常量集中管理
│   └── *.test.ts          各服务的 vitest 单测
├── config/                前端常量
│   ├── features.ts        前端 feature flags 副本（CI 校验与后端一致）
│   ├── sourceTypes.ts     信源类型 → 显示名 / 图标的映射
│   └── taskPromptDefaults.ts  日报 / 小时报 Prompt 默认值（与后端同步）
├── types/
│   └── index.ts           全局类型聚合导出
├── utils/                 前端共享工具
│   ├── apiError.ts        错误归一与展示
│   ├── datetime.ts        时区 / 相对时间
│   ├── sourceAuth.ts      信源认证 UI 帮手
│   └── sourceUrl.ts       URL canonicalize / 校验
└── styles/                样式
    ├── tailwind.css
    └── theme.css
```

#### `frontend/src/components/`

按业务页面分组（6 个目录共 60 个文件）：

```
components/
├── layout/                全局布局
│   ├── MainLayout.tsx     全局壳：导航 + 内容容器
│   ├── PageHeader.tsx
│   ├── Container.tsx
│   └── index.ts
├── common/                通用展示组件
│   ├── CategoryPillTabs.tsx
│   ├── PageHeroTitle.tsx
│   ├── PageLoading.tsx
│   ├── PanelLoading.tsx
│   ├── Spotlight.tsx
│   └── index.ts
├── ui/                    原子 UI 组件
│   ├── ApiKeyModal.tsx
│   ├── Badge.tsx
│   ├── ContentCard.tsx
│   ├── EmptyState.tsx
│   ├── SearchInput.tsx
│   ├── SectionNote.tsx
│   ├── SourceIcon.tsx
│   ├── StatCard.tsx
│   └── index.ts
├── Dashboard/             首页
│   ├── Dashboard.tsx
│   ├── DashboardHeader.tsx
│   ├── DashboardCategoryTabs.tsx
│   ├── DashboardDigestList.tsx
│   ├── DashboardItemCard.tsx
│   ├── DashboardQueueStatus.tsx
│   ├── DashboardSearchResults.tsx
│   ├── dashboardTypes.ts
│   ├── dashboardUtils.ts
│   └── dashboardUtils.test.ts
├── DigestView/            日报视图
│   └── DigestView.tsx
├── SourceList/            信源管理
│   ├── SourceListContainer.tsx
│   ├── SourceManager.tsx
│   ├── SourceEditorModal.tsx
│   ├── SourceImportModal.tsx
│   ├── FetchStatusIcon.tsx
│   ├── exportUtils.ts / .test.ts
│   ├── importUtils.ts / .test.ts
│   └── hooks/
│       ├── useSourceList.ts / .test.ts
│       ├── useSourceEditor.ts / .test.ts
│       └── useSourceImport.ts / .test.ts
└── Settings/              设置页
    ├── Settings.tsx / .test.tsx
    ├── AIModelTab.tsx
    ├── CredentialsTab.tsx
    ├── KeywordsTab.tsx / .test.tsx
    ├── keywordInputUtils.ts / .test.ts
    ├── ModelProvidersTab.tsx
    ├── TaskPromptsTab.tsx
    └── keywords/                  Keywords 子组件
        ├── KeywordBulkBar.tsx
        ├── KeywordColorSwatches.tsx
        ├── KeywordFormModal.tsx
        ├── keywordConstants.ts
        └── keywordHelpers.ts
```

---

## 4. `cli/pimctl/` CLI 包

```
cli/
├── __init__.py            标识 cli 为包
└── pimctl/
    ├── __init__.py        版本号 / 公共导出
    ├── __main__.py        `python -m cli.pimctl` 入口；./pimctl wrapper 调它
    ├── app.py             Click 主 group + 全部子命令注册
    │                       ↳ auth / system / sources / contents / settings / 等
    ├── client.py          HTTP 客户端：拼 X-API-Key、统一错误处理、--json 信封
    ├── config.py          配置文件解析（~/.pim/pimctl.toml）+ profile 切换
    └── output.py          人类可读 / JSON 双输出渲染
```

> `pimctl` 不依赖 `backend/app`，只通过 HTTP 跟后端通信，可独立打包分发。
> 完整命令树见 `docs/PIMCTL_REFERENCE.md`。

---

## 5. `docs/` 文档

```
docs/
├── ARCHITECTURE.md             架构总览（系统图 + 抓取时序图 + 服务边界表）
├── MODULE_BOUNDARIES.md        模块边界一页纸（三层 + 五领域 + 数据流 + 禁止依赖）
├── PROJECT_STRUCTURE.md        本文：每个文件/文件夹的作用
├── USER_GUIDE.md               最终用户使用手册
├── AGENT_GUIDE.md              Agent / 自动化集成指南（HTTP + pimctl）
├── PIMCTL_REFERENCE.md         pimctl 完整命令参考
├── API_GUIDE.md                API 端点 + 限速 + Prometheus rate() 样例
├── LOCAL_RUN.md                本地运行的全部细节（含 LaunchAgent / launchctl）
├── VPS_DEPLOY.md               VPS 部署（systemd / Nginx / 反向代理 / TLS）
├── CONTRIBUTING.md             贡献指南（branch / commit / PR / 测试要求）
├── TROUBLESHOOTING.md          故障排查手册
├── ADR-001-local-monolith.md         为什么选本地单体（vs 微服务）
├── ADR-002-digest-time-field.md      日报时间字段语义
├── ADR-003-auth-credentials.md       凭据加密与生命周期
├── ADR-004-feature-flags.md          Feature flags 单一事实源策略
├── ADR-005-module-boundaries.md      五领域 + 三层边界（已落地）
└── reviews/                          历史审计 / 设计文档归档
    ├── README.md                     归档说明 + 最新事实在哪儿看
    └── archive/
        ├── MODULE_REFACTOR_PLAN.md       Phase 0–7 完整实施记录 +
        │                                 旧路径 → 新路径映射 +
        │                                 仍保留的 shim 清单
        ├── CLI_SPEC.md                   ./pim 与 pimctl 早期设计规划
        │                                 （Phase 1+2 已落地；Phase 3
        │                                 MCP 兼容尚未实施）
        ├── audit-fix-plan.md             2026-04 第三版审计修复计划
        ├── AI_DECOUPLING_REFACTOR_PLAN.md  AI 解耦第一版计划
        ├── pim_aihot_upgrade_plan_2026-05-07.md
        │                                 AIHOT 借鉴升级计划（atoms / 3 小时报已落地）
        ├── audit-2026-05-02/             2026-05-02 第四版代码审计 11 件套
        │   ├── _audit-plan.md
        │   ├── 00-summary.md
        │   ├── 01-architecture.md
        │   ├── 02-security.md
        │   ├── 03-pipeline.md
        │   ├── 04-ai-processing.md
        │   ├── 05-api-design.md
        │   ├── 06-database.md
        │   ├── 07-scheduler.md
        │   ├── 08-testing.md
        │   ├── 09-frontend.md
        │   ├── 10-cli-ops.md
        │   └── 11-deps-standards.md
        ├── superpowers-plans/            2026-04 并行实施计划（按 Stream）
        │   ├── 2026-04-01-audit-fixes.md
        │   ├── 2026-04-01-stream1-frontend.md
        │   ├── 2026-04-01-stream2-backend.md
        │   ├── 2026-04-01-stream3-ci-docs.md
        │   └── 2026-04-01-stream4-tauri-observability.md
        └── superpowers-specs/
            └── 2026-04-01-phase2-3-design.md   Phase 2/3 设计文档
```

> `docs/` 顶层只保留**当前仍活的运维 / 架构 / 用户/Agent / 决策**文档；
> 已完成的实施计划（如 `MODULE_REFACTOR_PLAN.md`）与早期设计规划
> （如 `CLI_SPEC.md`）统一归档到 `reviews/archive/`，避免和最新事实混淆。

---

## 6. `.github/` CI

```
.github/
└── workflows/
    └── ci.yml         GitHub Actions 工作流：
                        - ruff check app
                        - python scripts/check_domain_imports.py --phase=7
                        - pytest -q --cov=app
                        - cd frontend && npm test && npm run build
                        - playwright test（如开关打开）
```

---

## 附录 A：被 `.gitignore` 的运行时产物

```
backend/venv/                   Python 虚拟环境（./pim setup 生成）
backend/.venv/                  备用 venv 位置
backend/coverage.xml            pytest-cov 产物
backend/celerybeat-schedule.db  历史 Celery 残留（项目用 APScheduler，不应再出现）
backend/pim.db                  本地 SQLite（默认在 ~/.pim/data/）
backend/requirements.txt.generated  uv export 临时产物
frontend/node_modules/          npm 依赖
frontend/dist/                  vite build 产物
frontend/playwright-report/     E2E 测试报告
frontend/test-results/          Playwright 失败截图 / trace
frontend/src-tauri/target/      Rust 构建产物
.pim-local-pids/                ./pim 的 PID 记录
.pim-local-logs/                ./pim 的日志
output/                         历史 RSS 批量导入 / podcast 封面缓存
__pycache__/                    全局 Python 字节码缓存
.pytest_cache/ .ruff_cache/
```

这些目录在 post-Phase-7 audit 中已完全从工作树清理；通过 `./pim setup`
+ `npm install` + `cargo build` 可重生。

## 附录 B：数据目录布局（`~/.pim/data/`）

```
data_dir/
├── pim.db                      主 SQLite 库（含 FTS5）
├── pim.db-wal / pim.db-shm     WAL 模式辅助文件
├── runtime-secrets.json        PIM_API_KEY + ENCRYPTION_KEY（自动生成）
├── metrics-checkpoint.json     优雅停机时的计数器序列化
├── pim.log                     主日志
├── cookies/                    按信源域名组织的 cookie 导入结果
└── storage-state/              Playwright storage_state 导出（登录态）
```

`DATA_DIR` 可通过 `backend/.env` 覆盖；备份通过 `./pim backup` 一并归档。
