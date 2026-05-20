# PIM CLI 规划规范

文档版本：v0.3（命令树已与实现同步）
日期：2026-04-12（上次同步）
适用范围：`Personal Info Monitor` 本地模式、服务器模式、Agent 调用模式

## 1. 背景与目标

当前项目已经具备两类天然入口：

- 面向人的入口：Web 前端 / Tauri
- 面向系统的入口：FastAPI 后端

后续希望把这套系统开源，并支持两种主要使用方式：

1. 本地 macOS 部署，用户通过前端/Tauri 使用
2. 服务器部署，Agent 通过 CLI 调用

因此需要引入正式的 CLI 规划，并把 CLI 视为“系统的第三个官方入口”。

CLI 的目标不是替代前端，而是提供一套：

- 稳定
- 无头
- 机器友好
- 可脚本化
- 可被 Agent 安全调用

的能力接口。

## 2. 设计原则

### 2.1 单一能力源

CLI 不直接复制业务逻辑，不直接操作数据库，不绕过后端服务层。

原则：

- CLI 调用后端 API
- 前端调用后端 API
- Tauri 启动本地后端后仍调用同一套 API

这样可以保证：

- 行为一致
- 权限模型一致
- 输出结构一致
- 测试路径一致

### 2.2 命令分层

建议明确拆分两个命令：

- `pim`：系统生命周期与运维
- `pimctl`：业务能力与 Agent 调用

不要把两类职责混在一个命令中。

### 2.3 默认支持机器调用

`pimctl` 从第一版开始就要支持：

- `--json`
- 稳定退出码
- 无交互调用
- 显式认证
- 可脚本组合

### 2.4 本地与远端一致

无论系统部署在：

- 本地 Mac
- Linux 服务器
- Tauri 背后本地服务

CLI 都应通过同样的请求模型访问能力层。

## 3. 产品形态

### 3.1 本地用户模式

典型路径：

```bash
./pim setup
./pim start
```

用户通过：

- 浏览器访问前端
- 或 Tauri 桌面端

同时也可以本地执行：

```bash
pimctl sources list
pimctl digest latest
```

### 3.2 服务器模式

典型路径：

- 后端常驻运行
- 可选部署前端
- `pimctl` 从远端访问服务器 API

例如：

```bash
pimctl --server https://pim.example.com --api-key xxx sources list --json
```

### 3.3 Agent 模式

Agent 通过 `pimctl --json` 调用，后续可扩展为 MCP server。

建议顺序：

1. 先做 CLI
2. CLI 规范稳定后，再包一层 MCP

原因：

- CLI 更容易验证
- CLI 更适合 shell / CI / cron / agent
- MCP 可以基于 CLI 或共享 client 库继续封装

## 4. 命令职责划分

## 4.1 `pim`

用途：系统生命周期管理、开发和部署辅助

建议保留的命令：

```bash
pim setup
pim start
pim stop
pim status
pim logs
pim doctor
```

说明：

- `setup`：创建环境、安装依赖、初始化 `.env`
- `start`：开发模式
- `start --prod`：单进程生产模式
- `stop` / `status` / `logs`：本地运行态管理
- `doctor`：自检命令，检查端口、依赖、数据库、配置、前端构建状态

`pim` 不负责具体业务操作，不负责列源、抓取、搜索内容。

## 4.2 `pimctl`

用途：业务能力入口，供人类脚本和 Agent 调用

建议命令树如下：

```bash
pimctl auth login [--set-default]
pimctl auth logout
pimctl auth whoami

# 系统状态
pimctl system health            # 无需认证，轻量存活探针 → GET /livez
pimctl system health-check      # 认证，检查 DB/调度器/磁盘 → GET /health
pimctl system metrics           # 请求统计、延迟、源运行指标 → GET /api/system/metrics
pimctl system queue             # 抓取/处理队列深度 → GET /api/system/queue
pimctl system stats             # Dashboard 摘要统计 → GET /api/dashboard/stats
pimctl system search-rebuild    # 重建全文搜索索引 → POST /api/system/search/rebuild
pimctl system doctor            # 完整系统诊断 → GET /api/system/doctor

# 监控源管理
pimctl sources list [--type] [--enabled] [--search] [--page] [--page-size]
pimctl sources get <id>
pimctl sources add --name --type --url [--extra-url] [--fetch-interval] [--disabled]
pimctl sources update <id> [--name] [--url] [--fetch-interval] [--enabled]
pimctl sources delete <id>
pimctl sources probe <id>
pimctl sources probe-url <url> [--type]
pimctl sources fetch <id>
pimctl sources fetch-all
pimctl sources export

# 内容管理
pimctl contents list [--source-id] [--source-type] [--read] [--favorited] [--archived] [--from-date] [--to-date] [--search] [--page] [--page-size]
pimctl contents get <id>
pimctl contents search <query> [--page] [--page-size]
pimctl contents delete <id>
pimctl contents reader <id> [--translate]
pimctl contents export-md
pimctl contents cleanup-low-signal [--apply] [--source-id] [--preview-limit]
pimctl contents cleanup-junk [--apply] [--source-id] [--preview-limit] [--no-binary] [--no-thin-rss]
pimctl contents mark-read <id>
pimctl contents mark-unread <id>
pimctl contents favorite <id>
pimctl contents unfavorite <id>
pimctl contents archive <id>
pimctl contents unarchive <id>

# 关键词监控
pimctl keywords list [--enabled]
pimctl keywords get <id>
pimctl keywords add <keyword> [--match-type] [--match-scope] [--description] [--color] [--notify] [--notify-email] [--disabled]
pimctl keywords batch-add <kw1> <kw2> ... [--match-type] [--match-scope] [--notify] [--notify-email]
pimctl keywords update <id> [--match-type] [--match-scope] [--enabled] [--notify] [--color] ...
pimctl keywords batch-update <id1> <id2> ... [--enabled] [--notify] [--color] ...
pimctl keywords delete <id>

# 日报/摘要
pimctl digest latest
pimctl digest stats
pimctl digest hourly-list [--date]
pimctl digest day <YYYY-MM-DD>
pimctl digest hour <YYYY-MM-DDTHH>

# 系统设置
pimctl settings get
pimctl settings limits
pimctl settings set --key <k> --value <v>
```

## 5. 全局参数规范

所有 `pimctl` 命令建议支持以下全局参数：

```bash
--server <url>
--api-key <key>
--json
--output <json|table|text>
--quiet
--timeout <seconds>
--profile <name>
```

建议行为：

- `--json`：强制 JSON 输出
- `--output`：控制展示形式
- `--quiet`：只输出必要数据，适合 shell 管道
- `--profile`：从本地配置文件读取指定配置

优先级建议：

1. CLI 参数
2. 环境变量
3. profile 配置
4. 默认值

## 6. 环境变量规范

建议新增并标准化以下环境变量：

```bash
PIM_SERVER
PIM_API_KEY
PIM_OUTPUT
PIM_PROFILE
PIM_TIMEOUT
```

示例：

```bash
export PIM_SERVER=https://pim.example.com
export PIM_API_KEY=xxxx
pimctl sources list --json
```

## 7. 本地配置文件

建议 CLI 使用独立配置文件，而不是直接依赖 `backend/.env`。

推荐位置：

```bash
~/.config/pim/config.toml
```

建议结构：

```toml
default_profile = "local"

[profiles.local]
server = "http://127.0.0.1:8000"
api_key = "xxxx"
output = "table"
timeout = 30

[profiles.prod]
server = "https://pim.example.com"
api_key = "yyyy"
output = "json"
timeout = 30
```

优点：

- 允许同时管理本地和远程环境
- 方便 agent 指定 profile
- 不污染后端运行配置

## 8. 认证设计

当前后端已经有基于 `X-API-Key` 的认证模型，因此 CLI 第一版直接复用即可。

### 8.1 请求头

CLI 请求统一附带：

```http
X-API-Key: <value>
```

### 8.2 登录命令

建议：

```bash
pimctl auth login --server http://127.0.0.1:8000 --api-key xxx
```

行为：

 - 验证 `/livez` 或一个轻量接口
- 成功后写入 profile

### 8.3 登出命令

```bash
pimctl auth logout --profile local
```

行为：

- 删除本地保存的 API Key
- 不影响服务器侧状态

## 9. 输出规范

## 9.1 人类友好模式

默认输出可以是：

- table
- 简明文本

例如：

```bash
$ pimctl sources list
ID         TYPE     NAME         STATUS   LAST_FETCHED
abc123     website  OpenAI Blog  ok       2026-03-30T10:00:00Z
```

## 9.2 机器友好模式

`--json` 是 Agent 调用主模式。

建议统一响应包络：

成功：

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "meta": {
    "server": "http://127.0.0.1:8000",
    "version": "2.0.0"
  }
}
```

失败：

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "auth_failed",
    "message": "Invalid or missing API key"
  },
  "meta": {
    "server": "http://127.0.0.1:8000"
  }
}
```

建议 CLI 统一包装后端返回，而不是把原始错误直接裸输出。

## 10. 退出码规范

建议固定退出码：

| 退出码 | 含义 |
|--------|------|
| `0` | 成功 |
| `1` | 通用失败 |
| `2` | 参数错误 |
| `3` | 认证失败 |
| `4` | 资源不存在 |
| `5` | 后端不可达 |
| `6` | 服务器返回非法响应 |

Agent 场景下，退出码比错误文案更重要。

## 11. 命令级设计

## 11.1 `system`

### `pimctl system health`

用途：

- 检查服务是否可达

映射：

- `GET /livez`

示例：

```bash
pimctl system health --json
```

### `pimctl system queue`

用途：

- 查看当前抓取/处理并发状态

映射：

- `GET /api/system/queue`

### `pimctl system stats`

用途：

- 查看 Dashboard 核心统计

映射：

- `GET /api/dashboard/stats`

## 11.2 `sources`

### `pimctl sources list`

建议参数：

```bash
--type <website|x|youtube|podcast>
--enabled <true|false>
--search <keyword>
--page <n>
--page-size <n>
```

映射：

- `GET /api/sources`

### `pimctl sources add`

建议参数：

```bash
--name <name>
--type <type>
--url <url>
--extra-url <url>   # 可重复
--category-id <id>
--fetch-interval <minutes>
--disabled
```

映射：

- `POST /api/sources`

### `pimctl sources update <id>`

用途：

- 更新源配置

映射：

- `PATCH /api/sources/{id}`

### `pimctl sources probe <id>`

用途：

- 重新探测已有源

映射：

- `POST /api/sources/{id}/probe`

### `pimctl sources probe-url <url>`

用途：

- 在不创建源的情况下探测 URL

映射：

- `POST /api/sources/probe`

### `pimctl sources fetch <id>`

映射：

- `POST /api/sources/{id}/fetch`

### `pimctl sources fetch-all`

映射：

- `POST /api/sources/fetch-all`

## 11.3 `contents`

### `pimctl contents list`

建议参数：

```bash
--source-id <id>
--source-type <type>
--category-id <id>
--read <true|false>
--favorited <true|false>
--archived <true|false>
--from <datetime>
--to <datetime>
--page <n>
--page-size <n>
```

映射：

- `GET /api/contents`

### `pimctl contents search <query>`

建议行为：

- 本质仍调用 `GET /api/contents?search=...`
- 只是 CLI 层封装成更直观命令

### `pimctl contents get <id>`

映射：

- `GET /api/contents/{id}`

### 状态修改命令

建议：

```bash
pimctl contents mark-read <id>
pimctl contents mark-unread <id>
pimctl contents favorite <id>
pimctl contents unfavorite <id>
pimctl contents archive <id>
pimctl contents unarchive <id>
```

实现方式：

- 优先复用已有 PATCH API
- 若后端已有语义化子路由，也可映射到专用接口

## 11.4 `digest`

### `pimctl digest latest`

用途：

- 获取最新一份 digest

实现建议：

- 先基于当前 digest API 封装
- 若后端暂无“latest”语义接口，可在 CLI 里查询当天或最近一天

### `pimctl digest day <date>`

参数示例：

```bash
pimctl digest day 2026-03-30 --json
```

### `pimctl digest hour <yyyy-mm-ddThh>`

此命令更适合 agent 和自动化流程。

## 11.5 `settings`

### `pimctl settings get`

映射：

- `GET /api/configs/settings`

### `pimctl settings set`

建议第一版只支持明确字段，不做自由 JSON patch：

```bash
pimctl settings set --translation-enabled true
pimctl settings set --provider ollama --model deepseek-r1:14b
```

内部再映射成标准 PATCH 请求。

## 12. 和现有后端 API 的映射关系

建议第一阶段尽量复用现有接口，不要求先改后端。

| CLI | HTTP API |
|-----|----------|
| `pimctl system health` | `GET /livez` |
| `pimctl system health-check` | `GET /health` |
| `pimctl system metrics` | `GET /api/system/metrics` |
| `pimctl system queue` | `GET /api/system/queue` |
| `pimctl system stats` | `GET /api/dashboard/stats` |
| `pimctl system search-rebuild` | `POST /api/system/search/rebuild` |
| `pimctl system doctor` | `GET /api/system/doctor` |
| `pimctl sources list` | `GET /api/sources` |
| `pimctl sources get` | `GET /api/sources/{id}` |
| `pimctl sources add` | `POST /api/sources` |
| `pimctl sources update` | `PATCH /api/sources/{id}` |
| `pimctl sources delete` | `DELETE /api/sources/{id}` |
| `pimctl sources probe` | `POST /api/sources/{id}/probe` |
| `pimctl sources probe-url` | `POST /api/sources/probe` |
| `pimctl sources fetch` | `POST /api/sources/{id}/fetch` |
| `pimctl sources fetch-all` | `POST /api/sources/fetch-all` |
| `pimctl sources export` | `GET /api/sources/export` |
| `pimctl contents list` | `GET /api/contents` |
| `pimctl contents get` | `GET /api/contents/{id}` |
| `pimctl contents search` | `GET /api/contents?search=...` |
| `pimctl contents delete` | `DELETE /api/contents/{id}` |
| `pimctl contents reader` | `GET /api/contents/{id}/reader` |
| `pimctl contents export-md` | `POST /api/contents/export-md` |
| `pimctl contents cleanup-low-signal` | `POST /api/contents/cleanup-low-signal` |
| `pimctl contents cleanup-junk` | `POST /api/contents/cleanup-junk` |
| `pimctl contents mark-read` | `POST /api/contents/{id}/read` |
| `pimctl contents mark-unread` | `PATCH /api/contents/{id}` |
| `pimctl contents favorite` | `POST /api/contents/{id}/favorite` |
| `pimctl contents unfavorite` | `PATCH /api/contents/{id}` |
| `pimctl contents archive` | `PATCH /api/contents/{id}` |
| `pimctl contents unarchive` | `PATCH /api/contents/{id}` |
| `pimctl keywords list` | `GET /api/keywords` |
| `pimctl keywords get` | `GET /api/keywords/{id}` |
| `pimctl keywords add` | `POST /api/keywords` |
| `pimctl keywords batch-add` | `POST /api/keywords/batch` |
| `pimctl keywords update` | `PATCH /api/keywords/{id}` |
| `pimctl keywords batch-update` | `PATCH /api/keywords/batch` |
| `pimctl keywords delete` | `DELETE /api/keywords/{id}` |
| `pimctl digest latest` | `GET /api/digest` |
| `pimctl digest stats` | `GET /api/digest/stats` |
| `pimctl digest hourly-list` | `GET /api/digest/hourly` |
| `pimctl digest day` | `GET /api/digest?date=...` |
| `pimctl digest hour` | `GET /api/digest/hourly/{hour}` |
| `pimctl settings get` | `GET /api/configs/settings` |
| `pimctl settings limits` | `GET /api/configs/settings` |
| `pimctl settings set` | `PATCH /api/configs/settings` |

## 13. 建议的实现结构

推荐在仓库中新增：

```text
cli/
├── pimctl/
│   ├── __main__.py
│   ├── app.py
│   ├── config.py
│   ├── output.py
│   ├── client.py
│   ├── commands/
│   │   ├── auth.py
│   │   ├── system.py
│   │   ├── sources.py
│   │   ├── contents.py
│   │   ├── digest.py
│   │   └── settings.py
│   └── schemas.py
```

建议：

- 使用 `Typer` 或 `Click`
- `client.py` 统一封装 HTTP 请求
- `output.py` 统一封装 text/table/json 输出
- `config.py` 统一管理 profile

## 14. 输出体验建议

### 人类模式

- 默认使用 table/text
- 关键字段简洁展示
- 可配 `--verbose`

### Agent 模式

- 默认最好直接 `--json`
- 不要混入无关提示语
- 不要把日志写到 stdout
- 诊断信息写 stderr

## 15. 安全边界

如果 CLI 将来要给 agent 用，必须坚持以下边界：

- 不提供任意 shell 执行能力
- 不把本地文件系统直接暴露为业务命令
- 不让 CLI 绕过后端认证
- 不在默认输出里泄露密钥

CLI 是“业务客户端”，不是“远程执行器”。

## 16. 版本策略

建议从一开始就给 CLI 明确版本语义：

```bash
pimctl --version
```

并在 JSON 输出里带：

- CLI version
- server version

这样 agent 侧能判断兼容性。

## 17. 第一阶段 MVP

建议先实现以下最小可用集：

```bash
pimctl system health --json
pimctl system queue --json

pimctl sources list --json
pimctl sources add ...
pimctl sources probe <id>
pimctl sources probe-url <url>
pimctl sources fetch <id>
pimctl sources fetch-all

pimctl contents list --json
pimctl contents search <query> --json

pimctl digest latest --json
pimctl settings get --json
```

这套已经足以支持：

- 人类脚本调用
- CI 任务
- Agent 自动化
- 后续 MCP 封装

## 18. 第二阶段扩展

第二阶段再补：

- `auth login/logout/whoami`
- `contents` 状态修改命令
- `settings set`
- `configs api-keys list`
- `configs auth list`
- `doctor`

## 19. 第三阶段：MCP 兼容

当 `pimctl` 稳定后，可以把资源抽象为 MCP tools：

- `list_sources`
- `probe_source`
- `fetch_source`
- `search_contents`
- `get_latest_digest`
- `get_system_health`

建议：

- MCP 和 CLI 共享同一个 Python client 层
- 不要做两套请求实现

## 20. 最终建议

当前阶段最推荐的路径：

1. 先把 `pim` 和 `pimctl` 的职责边界定死
2. 先做 `pimctl` 最小命令集
3. 所有命令默认支持 `--json`
4. CLI 只调用后端 API
5. 待 CLI 稳定后，再做 MCP/agent connector

这是当前最稳、投入产出比最高、也最适合开源演进的路线。
