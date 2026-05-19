# 后端服务

Personal Info Monitor 当前后端为单体 FastAPI 服务，负责：

- 监控源管理
- 内容抓取与处理
- SQLite 数据持久化
- APScheduler 定时任务
- 认证配置、系统设置、Dashboard 与 Digest API

## 当前技术栈

- FastAPI
- SQLAlchemy 2.x
- SQLite / aiosqlite
- APScheduler
- Playwright / Requests / aiohttp / Trafilatura

## 目录结构

```text
app/
├── api/          # REST API
├── collectors/   # RSS / 网站 / X / YouTube / Podcast 抓取器
├── models/       # ORM 模型
├── pipeline/     # 采集与处理编排
├── processors/   # 摘要、翻译、正文提取等
├── schemas/      # Pydantic 模型
├── services/     # 领域服务
├── tasks/        # 抓取、维护、邮件、小时报任务
└── utils/        # 通用工具
```

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

- 当前代码库不使用 Celery/Redis 作为主运行时。
- 运行时锁已优先使用数据库表，单进程内存锁只作为降级兜底。
