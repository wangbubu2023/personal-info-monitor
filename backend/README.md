# 后端服务

Personal Info Monitor 后端为单体 FastAPI 服务，负责：

- 监控源管理
- 内容抓取、归并、富化、原子化（atoms 旁路）
- SQLite 数据持久化
- APScheduler 定时任务
- 认证配置、系统设置、Dashboard 与 Digest API

## 当前技术栈

- FastAPI
- SQLAlchemy 2.x
- SQLite / aiosqlite + FTS5
- APScheduler
- Playwright / Requests / aiohttp / Trafilatura

## 目录结构（蓝图 Phase 0–7 后）

```text
app/
├── interfaces/                  # 外向适配层（HTTP / 未来 CLI、cron 入口）
│   └── http/                    # FastAPI 路由（含 sources/contents/digest/configs/system/keywords/dashboard）
├── domains/                     # 四个业务领域 + 跨域契约
│   ├── contracts/               # 跨领域 DTO 协议（fetch/ingest/enrich/sources/atoms）
│   ├── sources/                 # 源调度 + 状态 + 类型注册
│   ├── fetch/                   # 抓取
│   │   ├── auth/                # 浏览器/凭据/cookie 刷新
│   │   ├── collectors/          # rss / website / x_twitter / youtube / podcast
│   │   └── orchestrator.py      # fetch_source_async 入口
│   ├── ingest/                  # 归并入库主链
│   │   ├── build_content.py     # 把 FetchBatch 物化成 Content
│   │   ├── normalizer.py        # URL/标题/时间规范化
│   │   ├── dedupe.py            # 去重
│   │   ├── extractor.py         # 正文抽取（trafilatura/readability）
│   │   ├── quality.py / quality_metadata.py / fetch_acceptance.py
│   │   ├── score_vocab.py / score_rules.py / score_event.py / score_subjective.py
│   │   ├── scoring.py           # pim-score-v2 单篇合分（运维见 docs/SCORING_MODEL.md）
│   │   ├── summary_clean.py     # RSS/通讯摘要 boilerplate 清洗
│   │   ├── keywords/            # 关键词匹配 + 规则
│   │   ├── search.py / storage.py
│   │   ├── cleanup.py
│   │   └── finish.py            # ingest → enrich → atoms → notify 唯一汇合点
│   ├── enrich/                  # LLM 富化、reader、digest、通知
│   │   ├── content/             # 摘要/翻译触发与重处理
│   │   ├── reader/              # 正文加载 / 翻译 / NDJSON 流
│   │   ├── hourly/              # 每小时快报 / 可配置窗口简报
│   │   └── notifications/       # daily_digest / doctor / keyword_alert
│   └── atoms/                   # 新闻原子库（ATOMS_ENABLED）；atoms + atom_relations 表
├── platform/                    # 横切基础设施（禁止依赖 domains）
│   ├── auth/                    # API key / cookies / 凭据加解密
│   ├── browser/                 # Playwright pool
│   ├── config/                  # Settings + system_settings DB-cache
│   ├── export/                  # markdown 导出
│   ├── health/                  # /livez /health 探针
│   ├── llm/                     # summarizer / translator / 提供商代理
│   ├── locks/                   # 进程级 + DB 级运行时锁
│   ├── notifications/           # SMTP 传输
│   ├── observability/           # logger / metrics / tracing
│   ├── persistence/             # SQLAlchemy engine / session
│   ├── runtime/                 # 启动钩子、shutdown checkpoint
│   ├── security/                # 加密、SSRF 过滤
│   └── workers/                 # 有界任务队列
├── models/                      # ORM 实体
├── schemas/                     # Pydantic 模型
├── ai/, services/, processors/, tasks/, pipeline/, utils/
│                                # 历史 shim：仍保留是为了已有 `patch()` target 与
│                                # 极少数尚未迁完的内部调用。新代码必须直接走
│                                # interfaces / domains / platform 三层。
├── api/                         # sys.modules 别名，把 app.api.* 解析到
│                                # app.interfaces.http.*（同一模块对象）
├── background.py, main.py, scheduler.py, features.py, config.py, database.py, auth.py
│                                # 顶层入口或薄 shim
└── data/                        # 静态 JSON 资源（model_providers.json）
```

详细边界与导入约束见 `docs/MODULE_BOUNDARIES.md` 与
`backend/scripts/check_domain_imports.py`（CI 会用 `--phase=7` 检查）。

## 本地开发

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
./.venv/bin/alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

首次运行会自动创建 `DATA_DIR` 对应的数据目录，并在 `DATA_DIR/runtime-secrets.json` 中生成稳定的运行时密钥。`backend/.env` 只用于可选配置，不再由启动流程回写敏感信息。

## 数据库迁移

当前 schema 由 Alembic 管理，应用启动时会自动执行 `upgrade head`。如需手动迁移：

```bash
cd backend
./.venv/bin/alembic upgrade head
```

## 测试

```bash
cd backend
./.venv/bin/pytest -q
```

## Lint & 技术债看板

CI 在后端跑 `ruff check app`，目前只启用以下高信号规则：

| 规则   | 说明                                                           |
|--------|--------------------------------------------------------------|
| BLE001 | 盲目 `except Exception:` 吞错（新代码一律禁止）               |
| B904   | `except` 中 `raise Err(...)` 忘记 `from` 丢失 traceback        |
| B023   | 闭包捕获循环变量                                              |
| F821   | 引用未定义的名字                                              |
| F811   | 未使用的重复定义                                              |

### 存量 BLE001 baseline

`pyproject.toml` 的 `[tool.ruff.lint.per-file-ignores]` 中列出了审计期（2026-04）仍存在盲目 except 的历史文件。新增的文件**不允许**进入这张列表。

回收策略：一次修一个文件，把所有 `except Exception as exc:` 改成：

- 明确捕获具体异常（如 `aiohttp.ClientError`、`sqlalchemy.exc.OperationalError`），或
- 保留宽异常但改为 `logger.exception(...)` + 重新 raise 到合适的位置

修复完后从 per-file-ignores 删除对应条目，跑 `ruff check --select BLE001 app/<path>` 确认本地零违规，再提 PR。

本地运行：

```bash
cd backend
./.venv/bin/ruff check app
```

## 说明

- 当前代码库不使用 Celery/Redis 作为主运行时（APScheduler + 内置有界 TaskQueue）。
- 运行时锁优先使用数据库表（`app/platform/locks/`），单进程内存锁只作为降级兜底。
- LLM 产品开关与全局暂停由持久化 system settings 控制；
  `PIM_AI_HARD_DISABLE=true` 是部署级紧急停机开关。旧版
  `AI_PROCESSING_ENABLED` / `ENRICH_*` / `PIM_SCORE_LLM_SUBJECTIVE`
  只参与一次性事务迁移，迁移状态保存在 `ai_policy_migration_state`。
- 主观评分是零权重 Shadow：输入资格、800 字正文上限、并发 2、Token 预算和
  `input_hash + model_version + prompt_version` 缓存均在 Provider 调用前执行。
- 新闻原子库（Schema v2）默认关闭：`ATOMS_ENABLED=true` 启用提取与 `/atoms` API；`ATOMS_RELATIONS_ENABLED` 控制跨文关系（P2）
  显式开启；开启后也只是 `finish_content` 旁路的 best-effort 写入，
  永远不阻塞 ingest 主链。
