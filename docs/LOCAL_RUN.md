# 无 Docker 本地运行说明

本文档描述当前项目的真实本地运行方式。  
当前主运行路径为：

- 前端开发服务器：`localhost:3000`
- 后端 API：`127.0.0.1:8000`
- 生产/单进程模式：FastAPI 在 `127.0.0.1:8000` 同时提供 API 与静态前端

## 前置要求

- Python 3.11+
- Node.js 18+
- npm

## 方式一：推荐使用项目 CLI

### 初始化

```bash
./pim setup
```

默认会安装浏览器抓取所需的 bundled Chromium，并做一次启动 smoke test。Linux 上还会尝试安装
Chromium 系统运行库；如果这些依赖由系统镜像预装，可使用 `--skip-playwright-deps`。

不需要浏览器登录/动态网页抓取时，可以跳过 Chromium 下载：

```bash
./pim setup --skip-playwright
```

### 更新

```bash
./pim upgrade
```

该命令会拒绝覆盖本地未提交改动；更新前会先备份已有 SQLite 数据库和运行时密钥。

### 开发模式

```bash
./pim start
```

启动后：

- 浏览器访问：`http://localhost:3000`
- API：`http://127.0.0.1:8000`

### 生产/单进程模式

```bash
./pim start --prod
```

启动后访问：

- `http://127.0.0.1:8000`

## 方式二：手动启动

### 1. 后端

推荐使用 [`uv`](https://docs.astral.sh/uv/)（与 CI 一致）：

```bash
cd backend
uv sync --extra dev           # 按 uv.lock 创建 .venv 并安装依赖（含 pytest/ruff）
. .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

> 也可退回 `pip` 路径，使用锁定好的 `requirements.txt`：
>
> ```bash
> cd backend
> python3 -m venv .venv && . .venv/bin/activate
> pip install -r requirements.txt
> ```
>
> `requirements.txt` 由 `pyproject.toml` + `uv.lock` 自动导出，**请勿手改**。
> 需要新增/升级依赖时：改 `pyproject.toml` → `uv lock` → `uv export --no-hashes --no-dev --no-emit-project --format requirements.txt > requirements.txt`。

### 2. 前端

```bash
cd frontend
npm install
VITE_API_URL=http://127.0.0.1:8000 npm run dev
```

### 3. 生产构建

```bash
cd frontend
npm run build
cd ../backend
. .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

生产模式下由 FastAPI 直接托管 `frontend/dist`。

## 环境变量

主配置文件：`backend/.env`

常用项：

| 变量 | 说明 |
|------|------|
| `PIM_API_KEY` | API 认证密钥 |
| `ENCRYPTION_KEY` | 加密认证信息 |
| `JWT_SECRET_KEY` | JWT/签名密钥 |
| `DATA_DIR` | SQLite 数据目录 |
| `PIM_PUBLIC_URL` | 公网部署时的浏览器访问地址，用于 `./pim bootstrap-url` |
| `FETCH_CONCURRENCY` | 抓取并发；同步 DB 连接池会自动按该值扩容，并额外保留 10 个连接 |
| `PIM_AI_HARD_DISABLE` | 部署级 LLM 紧急停机开关（默认 false）；产品开关在 Web 设置中管理 |
| `OPENAI_API_KEY` | 可选，云端模型 Key |
| `RSSHUB_URL` | 可选，RSSHub 地址 |

模板文件：`backend/.env.example`

## 测试

```bash
cd backend
./.venv/bin/pytest -q
```

## 说明

- 当前项目不要求 PostgreSQL、Redis、Celery（主路径为 SQLite 与单进程 FastAPI）。
- 数据库结构变更由 **Alembic** 管理：应用启动时会自动执行迁移；本地也可在 `backend` 目录执行 `./.venv/bin/alembic upgrade head`。完整说明见根目录 `README.md` 中的「数据库迁移」。
- 如需桌面模式，可在 `frontend/src-tauri/` 下继续使用 Tauri 开发/打包。
