# Personal Info Monitor (PIM)

个人化资讯监控与摘要系统：聚合网站、RSS、X、YouTube、播客等内容源，支持抓取探测、关键词监控、摘要与翻译，以及日报/小时报展示。

## 架构

```
后端  FastAPI + SQLAlchemy + SQLite + APScheduler  →  http://127.0.0.1:8000
前端  Vite + React + Ant Design                   →  http://localhost:3000  (仅 dev 模式)
桌面  Tauri                                        →  tauri.localhost / localhost:1420
```

**固定端口**（不会变）：

| 服务 | 地址 | 说明 |
|------|------|------|
| 后端 API | `http://127.0.0.1:8000` | dev / prod / 服务模式均相同 |
| 前端 dev server | `http://localhost:3000` | 仅开发模式，`strictPort: true` |
| Tauri 桌面应用 | `http://tauri.localhost` | 桌面端，连接同一后端 |

```mermaid
flowchart LR
    A["Collectors"] --> B["Pipeline"]
    B --> C["Processors"]
    C --> D["SQLite"]
    D --> E["FastAPI :8000"]
    E --> F["React :3000 / Tauri"]
    G["APScheduler"] --> A
```

---

## 启动方式

### 方式一：后台服务（推荐日常使用）

**一次性安装**，之后登录自动启动，无需打开终端：

```bash
./pim setup            # 首次安装依赖（只需执行一次）
./pim install-service  # 注册 macOS LaunchAgent，立即启动
```

安装后服务在后台持续运行，关闭终端不受影响，重新登录自动恢复。

常用管理命令：

```bash
./pim status             # 查看运行状态（含 PID）
./pim stop               # 暂停服务（不卸载，下次登录仍会自动启动）
./pim install-service    # 恢复/重装服务
./pim uninstall-service  # 彻底移除，不再自动启动
./pim logs               # 实时查看日志
```

服务启动后访问：`http://127.0.0.1:8000`

---

### 方式二：手动启动（终端）

**开发模式**（前后端热重载，推荐开发时使用）：

```bash
./pim start
```

- 后端：`http://127.0.0.1:8000`（带 `--reload`）
- 前端：`http://localhost:3000`（Vite dev server，`/api` 自动代理到后端）
- 关闭终端后进程停止

**生产模式**（后台运行，不依赖终端）：

```bash
./pim start --prod   # 后台启动，日志写入 ~/.pim/data/pim.log
./pim stop           # 停止
./pim status         # 查看状态
./pim logs           # 查看日志
```

- 单进程，FastAPI 同时提供 API 与已构建的前端静态资源
- 访问：`http://127.0.0.1:8000`

---

### 方式三：手动逐步启动（不使用 pim 脚本）

**后端**：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
.venv/bin/alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

**前端**（另开终端）：

```bash
cd frontend
npm install
npm run dev       # → http://localhost:3000
# 生产构建：
npm run build     # 构建到 dist/，由后端 FastAPI 提供
```

---

## 初始化（首次）

要求：Python 3.11+、Node.js 18+、npm

```bash
./pim setup
```

完成：创建 `.venv`、安装后端依赖、安装 Playwright Chromium、生成 `backend/.env` 模板、初始化运行时密钥、安装并构建前端。

---

## pimctl — Agent / 脚本调用

`pimctl` 是面向脚本和 Agent 的业务命令层，直接调用 API，不需要进入项目目录。

**前置：确认服务已在运行**（任意方式启动均可）：

```bash
curl http://127.0.0.1:8000/livez   # → {"status":"ok"}
```

**认证**：

```bash
./pimctl auth login --server http://127.0.0.1:8000 --api-key <your-key>
# API Key 查看方式：
./pim logs | grep "API Key"
# 或直接读取：
cat ~/.pim/data/runtime-secrets.json
```

**常用命令**：

```bash
# 系统
./pimctl system health --json
./pimctl system metrics --json

# 内容源
./pimctl sources list --json
./pimctl sources add --url https://example.com/feed --type rss

# 内容
./pimctl contents search "openai" --json
./pimctl contents list --unread --json

# 设置
./pimctl settings get --json
./pimctl settings limits --json
```

完整规格见 [docs/CLI_SPEC.md](docs/CLI_SPEC.md)。

---

## API

- Swagger UI：`http://127.0.0.1:8000/docs`
- ReDoc：`http://127.0.0.1:8000/redoc`
- 探活：`GET /livez`
- 健康检查：`GET /health`（需要 `X-API-Key`）
- 运行指标：`GET /api/system/metrics`（需要 `X-API-Key`）
- Prometheus：`GET /metrics`（需要 `X-API-Key`）
- 手写 API 指南：`docs/API_GUIDE.md`

所有 `/api` 路由均需要 `X-API-Key` header。

---

## 配置

主配置文件：`backend/.env`（从 `backend/.env.example` 复制）。

运行时密钥（`PIM_API_KEY`、`ENCRYPTION_KEY`）自动生成并保存在 `~/.pim/data/runtime-secrets.json`，不写回 `.env`。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATA_DIR` | `~/.pim/data` | SQLite 数据库与日志目录 |
| `FETCH_CONCURRENCY` | `20` | 并发抓取数 |
| `AI_PROCESSING_ENABLED` | `true` | AI 总开关（已 deprecated，Phase 7 移除；保留作为 master kill switch） |
| `ENRICH_AUTO_ON_INGEST` | `false` | ingest 完成时是否自动触发 enrich 流水线（Phase 4 step 8） |
| `ENRICH_SUMMARY_ENABLED` | `true` | 是否允许 Summarizer 调 LLM 生成摘要 |
| `ENRICH_TRANSLATE_ENABLED` | `true` | 是否允许 Translator 调 LLM 做翻译 |
| `OPENAI_API_KEY` | — | 云端模型（可选） |
| `RSSHUB_URL` | `https://rsshub.app` | RSSHub 实例地址 |
| `CORS_ORIGINS` | 见下 | 允许的前端来源 |
| `TRUSTED_PROXY_IPS` | — | 可信反向代理 IP（逗号分隔），设置后从 `X-Real-IP` 读取真实客户端 IP，VPS 部署时必填，见 `docs/VPS_DEPLOY.md` |
| `API_RATE_LIMIT_PER_MINUTE` | `120` | 每分钟每 IP 最大请求数，`0` 表示关闭 |

默认 CORS 白名单（已覆盖所有启动模式）：
- `http://localhost:3000`、`http://127.0.0.1:3000`（前端 dev）
- `http://tauri.localhost`、`https://tauri.localhost`、`http://localhost:1420`（Tauri 桌面）

---

## 数据库迁移

应用启动时自动执行 Alembic 迁移。手动执行：

```bash
cd backend && .venv/bin/alembic upgrade head
```

回滚：

```bash
./pim rollback <revision>
```

---

## 备份

```bash
./pim backup
```

生成 SQLite 热备份并归档 `.env` 与 `runtime-secrets.json` 到 `~/.pim/backups/`。

---

## 测试

```bash
# 后端（覆盖率 ≥ 60%）
cd backend && .venv/bin/pytest -q --cov=app

# 前端
cd frontend && npm test && npm run build
```

---

## 文档

| 文档 | 路径 |
|------|------|
| **模块化重构方案**（五领域模块 + 迁移计划） | [`docs/MODULE_REFACTOR_PLAN.md`](docs/MODULE_REFACTOR_PLAN.md) |
| **模块边界一页纸** | [`docs/MODULE_BOUNDARIES.md`](docs/MODULE_BOUNDARIES.md) |
| **用户使用指南** | [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) |
| **Agent 集成指南** | [`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md) |
| **pimctl 命令参考** | [`docs/PIMCTL_REFERENCE.md`](docs/PIMCTL_REFERENCE.md) |
| 本地运行详细说明 | `docs/LOCAL_RUN.md` |
| VPS 部署 | `docs/VPS_DEPLOY.md` |
| API 使用指南 | `docs/API_GUIDE.md` |
| CLI 规格 | `docs/CLI_SPEC.md` |
| 故障排查 | `docs/TROUBLESHOOTING.md` |
| 架构决策记录 | `docs/ADR-001-local-monolith.md` |
| 后端说明 | `backend/README.md` |

---

## 故障排查

| 问题 | 处理 |
|------|------|
| 服务没起来 | `./pim logs` 查看最近错误 |
| 端口 8000 被占用 | `lsof -i :8000` 找占用进程，kill 后服务自动恢复 |
| API Key 忘了 | `cat ~/.pim/data/runtime-secrets.json` |
| pimctl 认证失败 | `./pimctl auth login` 重新登录 |
| LaunchAgent 没启动 | `./pim status` 查状态，`./pim logs` 看日志 |

详见 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)。

---

## 许可证

[MIT](LICENSE)
