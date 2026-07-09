# Personal Info Monitor (PIM)

> 本地优先的个人资讯监控系统。PIM 把 RSS、网站、X、YouTube、Podcast 等来源统一抓取、去重、评分、摘要和归档，并提供 Web UI、桌面端、`pimctl` CLI 与远程部署运维能力。

当前版本：**1.5.0**

## 1.5.0 重点

- **Auth Assistant**：在 VPS 上生成一次性配对码，本地桌面助手采集浏览器登录态后上传到远程 PIM。它只拿到受限设备令牌，不会接触 PIM 管理 API Key。
- **站点抓取兜底增强**：普通网站解析不再因为先命中 5 条内容就跳过全页 `<a href>` 扫描；默认最多保留 50 条候选，更适合财联社这类首页要闻和快讯混排页面。
- **X 探测认证修复**：源级 `metadata/auth_config` 中的 `auth_token`、`ct0` 会优先参与 probe，不再只看全局配置。
- **重复内容标记**：新增 `is_duplicate`、`duplicate_of` 字段，列表默认收敛同标题/同事件重复项，历史 `duplicate_group_id` 也会兼容折叠。
- **更新检查**：Web 侧栏和系统维护页会读取 GitHub Releases，发现新版本时引导升级。
- **抓取流水线降阻塞**：若干数据库提交、存储与重复检测路径移到后台线程执行，减少异步调度被同步 I/O 卡住的概率。

## 架构速览

```mermaid
flowchart LR
  Sources["RSS / Website / X / YouTube / Podcast"] --> Fetch["domains/fetch"]
  Fetch --> Ingest["domains/ingest<br/>normalize · dedupe · storage"]
  Ingest --> Enrich["domains/enrich<br/>summary · translate · digest"]
  Ingest --> Atoms["domains/atoms<br/>optional structured events"]
  Enrich --> DB[("SQLite + FTS5")]
  Atoms --> DB
  DB --> API["FastAPI :8000"]
  API --> Web["React Web / Tauri"]
  API --> CLI["pimctl"]
  Assistant["PIM Auth Assistant"] --> API
  Scheduler["APScheduler"] --> Fetch
  Scheduler --> Enrich
```

- 后端：FastAPI + SQLAlchemy 2 + SQLite/FTS5 + APScheduler。
- 前端：Vite + React + Ant Design，Tauri 提供桌面壳。
- CLI：`pimctl` 只通过 HTTP API 工作，不直接读写数据库。
- 数据目录：默认 `~/.pim/data`，包含 SQLite、运行时密钥、浏览器会话、日志和指标 checkpoint。

更完整的边界说明见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)、[`docs/MODULE_BOUNDARIES.md`](docs/MODULE_BOUNDARIES.md) 和 [`docs/PROJECT_STRUCTURE.md`](docs/PROJECT_STRUCTURE.md)。

## 快速开始

要求：Python 3.11+、Node.js 18+、npm。构建 Tauri 桌面端还需要 Rust。

```bash
git clone --depth 1 https://github.com/wangbubu2023/personal-info-monitor.git
cd personal-info-monitor
./pim setup
./pim start
```

首次 `setup` 会安装后端、前端和浏览器依赖，并生成：

- `backend/.env`
- `~/.pim/data/runtime-secrets.json`
- `~/.pim/data/pim.db`

新安装默认关闭 outbound LLM。配置模型后，再打开 `AI_PROCESSING_ENABLED` 与需要的 `ENRICH_*` 开关。

## 常用运行方式

### 本机开发

```bash
./pim start         # 后端 :8000 + 前端 :3000
./pim start --prod  # 单进程服务，后端同时托管已构建前端
./pim stop
./pim status
./pim logs
```

### macOS 后台服务

```bash
./pim install-service
./pim status
./pim upgrade
./pim uninstall-service
```

`./pim upgrade` 会执行备份、`git pull --ff-only`、依赖刷新、前端构建和服务重启。tag/detached 部署可用：

```bash
./pim upgrade --no-pull
```

## Web UI

默认入口：

- 后端 API：`http://127.0.0.1:8000`
- 开发前端：`http://127.0.0.1:3000`
- 生产 Web：`http://127.0.0.1:8000`

主要页面：

- 资讯流：搜索、筛选、查看正文与摘要。
- 信源管理：添加 RSS、网站、X、YouTube、Podcast，查看抓取健康状态。
- 设置：抓取、凭据、Auth Assistant、智能引擎、任务提示词、维护升级。
- 系统维护：备份、升级、支持包、GitHub Release 更新检查。

## Auth Assistant

Auth Assistant 用来解决“PIM 跑在 VPS，但登录态只能在本地浏览器里拿到”的问题。

推荐流程：

1. 在远程 PIM Web 打开 `设置 -> Auth Assistant`。
2. 生成 10 分钟有效的一次性配对码。
3. 在本地打开 `auth-assistant/` 应用，填入远程 PIM 地址和配对码完成连接。
4. 本地采集 X、WSJ、NYTimes 等站点登录态。
5. 上传到 PIM，后端会导入为 Auth Config / Browser Session，并自动绑定匹配信源。

安全边界：

- 配对码一次性使用，过期失效。
- 本地助手只保存设备令牌，不能调用管理 API。
- PIM 端可随时在设置页移除已配对设备。

开发运行：

```bash
cd auth-assistant
npm install
npm run dev
```

桌面采集命令依赖仓库根目录的 `./pim capture-session`。开发时如果助手不在仓库内运行，可设置 `PIM_PROJECT_ROOT=/path/to/personal-info-monitor`。

## 网站抓取策略

PIM 的网站源会先尝试结构化解析、列表发现和站点规则，再用全页链接兜底。

1. 默认 discovery 会从来源 URL 扫描同域文章链接。
2. 全页 `<a href>` 兜底默认最多补到 50 条文章候选。
3. 可通过源 metadata 调整：

```json
{
  "fallback_link_max": 80,
  "discovery_default_max_links": 50,
  "discovery": {
    "mode": "listing",
    "listing_urls": ["https://www.example.com/news"],
    "max_links": 50,
    "url_allow_patterns": ["/detail/", "/article/"]
  }
}
```

对财联社这类页面，兜底扫描会覆盖中间要闻区和右侧电报区，而不再只保存最先解析到的少量卡片。

## X 与登录态

X 抓取优先使用浏览器登录态 Cookie 的 GraphQL 路径，然后才尝试 RSSHub / Nitter。

可用来源：

- 源级 `metadata.auth_config` 或绑定的 Auth Config。
- 全局 `X_AUTH_TOKEN` / `X_CT0_TOKEN`。
- 显式配置的官方 X API fallback。

官方 X API 不会因为设置了 `X_BEARER_TOKEN` 自动启用；只有单个信源设置 `metadata.strategy=api` 或 `metadata.allow_x_api_fallback=true` 时才会调用。

## 配置

主配置在 `backend/.env`。运行时密钥在 `~/.pim/data/runtime-secrets.json`，不会回写到 `.env`。

| 变量 | 默认 | 说明 |
|---|---|---|
| `DATA_DIR` | `~/.pim/data` | SQLite、日志、浏览器会话目录 |
| `PIM_PUBLIC_URL` | 空 | VPS / 反向代理公网地址 |
| `FETCH_CONCURRENCY` | `20` | 并发抓取上限 |
| `AI_PROCESSING_ENABLED` | `false` | LLM 总开关 |
| `ENRICH_AUTO_ON_INGEST` | `false` | 入库后自动摘要/翻译 |
| `ENRICH_SUMMARY_ENABLED` | `false` | 允许生成摘要 |
| `ENRICH_TRANSLATE_ENABLED` | `false` | 允许生成翻译 |
| `ATOMS_ENABLED` | `false` | 结构化事件层 |
| `OPENAI_API_KEY` | 空 | 云端模型凭据 |
| `RSSHUB_URL` | `https://rsshub.app` | RSSHub 实例 |
| `X_BEARER_TOKEN` | 空 | 官方 X API fallback 凭据 |
| `PIM_UPDATE_CHECK_REPO` | `wangbubu2023/personal-info-monitor` | GitHub Release 更新检查仓库 |
| `API_RATE_LIMIT_PER_MINUTE` | `120` | API 限速，`0` 关闭 |
| `PIM_BROWSER_BACKEND` | `patchright` | 浏览器后端，可设为 `playwright` |
| `PIM_PLAYWRIGHT_CHANNEL` | `none` | 可设为 `chrome` 使用系统 Chrome |

默认 CORS 覆盖 `localhost:3000`、`127.0.0.1:3000`、`tauri.localhost` 和 Tauri 开发端口。

## pimctl

登录一次后，后续命令可省略 `--server` 和 `--api-key`。

```bash
jq -r .PIM_API_KEY ~/.pim/data/runtime-secrets.json
./pimctl auth login --server http://127.0.0.1:8000 --api-key <key>

./pimctl system health --json
./pimctl sources list --json
./pimctl sources add --url https://example.com/feed --type rss
./pimctl contents search "AI" --json
./pimctl digest latest --json
./pimctl settings get --json
```

完整命令见 [`docs/PIMCTL_REFERENCE.md`](docs/PIMCTL_REFERENCE.md)，Agent 集成见 [`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md)。

## API

| 端点 | 鉴权 | 用途 |
|---|---|---|
| `GET /livez` | 否 | 探活 |
| `GET /health` | `X-API-Key` | 健康检查 |
| `GET /api/system/metrics` | `X-API-Key` | JSON 指标 |
| `GET /metrics` | `X-API-Key` | Prometheus 文本 |
| `GET /api/system/update-check` | `X-API-Key` | GitHub Release 更新检查 |
| `POST /api/auth-assistant/pairing-tokens` | `X-API-Key` | 创建 Auth Assistant 配对码 |
| `POST /api/auth-assistant/pair` | 配对码 | 本地助手换取设备令牌 |
| `POST /api/auth-assistant/auth-bundles/import` | 设备令牌 | 上传单个登录态 bundle |
| `POST /api/auth-assistant/auth-exports/import` | 设备令牌 | 上传登录态 zip |
| `GET /docs` / `GET /redoc` | 否 | Swagger / ReDoc |

所有普通 `/api/*` 路由都要求 `X-API-Key`。Auth Assistant 的导入端点使用受限设备令牌。

## 数据库、备份与回滚

```bash
./pim backup
./pim upgrade
./pim rollback <revision>
cd backend && alembic upgrade head
```

应用启动时会自动执行 `alembic upgrade head`。

重要迁移：

- `20260708_0027_content_duplicate_markers.py`：为内容表添加重复标记并回填历史同组数据。
- `20260709_0028_auth_assistant_pairing.py`：新增 Auth Assistant 配对、设备和导入审计表。

VPS 首次登录 Web UI 时可生成公网引导链接：

```bash
./pim bootstrap-url --origin https://your-domain.com
```

本地采集并上传远程登录态：

```bash
./pim login-sync https://example.com --remote pim@your-vps --remote-pim ~/personal-info-monitor
```

## 测试与质量门

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest
PYTHONPATH=. .venv/bin/ruff check app
PYTHONPATH=. .venv/bin/python scripts/check_domain_imports.py --phase=7

cd ../frontend
npm test
npm run build

cd ../auth-assistant
npm run build
```

CI 运行后端 lint、架构边界、pytest，前端 lint、Vitest、npm audit，以及安全扫描。Playwright E2E 仍建议本地按需执行。

## 发布

发布稳定版本时保持三个版本源一致：

- `backend/pyproject.toml`
- `frontend/package.json`
- `frontend/src-tauri/tauri.conf.json` / `frontend/src-tauri/Cargo.toml`

然后提交、打 tag，并创建 GitHub Release。Web 更新检查依赖 GitHub Releases 的 `latest` 端点，仅推 tag 不会触发“发现新版本”提示。

```bash
git commit -m "release: 1.5.0"
git tag -a v1.5.0 -m "Release 1.5.0"
git push origin main v1.5.0
gh release create v1.5.0 --title "v1.5.0" --notes-file /tmp/pim-release-notes.md
```

## 文档地图

| 用途 | 文档 |
|---|---|
| 架构总览 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| 项目结构 | [`docs/PROJECT_STRUCTURE.md`](docs/PROJECT_STRUCTURE.md) |
| 模块边界 | [`docs/MODULE_BOUNDARIES.md`](docs/MODULE_BOUNDARIES.md) |
| 用户指南 | [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) |
| Agent 集成 | [`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md) |
| pimctl 参考 | [`docs/PIMCTL_REFERENCE.md`](docs/PIMCTL_REFERENCE.md) |
| 本地运行 | [`docs/LOCAL_RUN.md`](docs/LOCAL_RUN.md) |
| VPS 部署 | [`docs/VPS_DEPLOY.md`](docs/VPS_DEPLOY.md) |
| API 指南 | [`docs/API_GUIDE.md`](docs/API_GUIDE.md) |
| 故障排查 | [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) |
| 贡献规则 | [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) |

## 故障排查速查

| 现象 | 处理 |
|---|---|
| 服务没起来 | `./pim status` 看 PID，`./pim logs` 看最近错误 |
| 8000 端口被占 | `lsof -i :8000` 找占用进程后处理 |
| API Key 忘了 | `jq -r .PIM_API_KEY ~/.pim/data/runtime-secrets.json` |
| `pimctl` 认证失败 | `./pimctl auth login` 重新登录 |
| schema 不一致 | `cd backend && alembic upgrade head` |
| 远程站点抓不到登录内容 | 用 Auth Assistant 重新采集并上传对应站点登录态 |
| X probe 失败 | 检查源级 Auth Config 或全局 `X_AUTH_TOKEN` / `X_CT0_TOKEN` |

## License

[MIT](LICENSE)
