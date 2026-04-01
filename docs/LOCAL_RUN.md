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

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

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
| `FETCH_CONCURRENCY` | 抓取并发 |
| `AI_PROCESSING_ENABLED` | 是否启用 AI 处理 |
| `OPENAI_API_KEY` | 可选，云端模型 Key |
| `RSSHUB_URL` | 可选，RSSHub 地址 |

模板文件：`backend/.env.example`

## 测试

```bash
cd backend
./.venv/bin/pytest -q
```

## 说明

- 当前项目不要求 PostgreSQL、Redis、Celery、Alembic。
- 如需桌面模式，可在 `frontend/src-tauri/` 下继续使用 Tauri 开发/打包。
