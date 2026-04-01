# API 使用指南

本项目除了 FastAPI 自动生成的 `/docs` 和 `/redoc`，还保留一份手写的使用说明，方便第三轮 review、脚本调用和排障时快速核对认证流程与典型请求。

## 认证方式

所有 `/api/*` 端点默认都需要 `X-API-Key` 请求头。

示例：

```bash
curl -H "X-API-Key: <your-api-key>" \
  http://127.0.0.1:8000/api/system/metrics
```

公开端点：

- `GET /livez`

受保护端点：

- `GET /health`
- `GET /metrics`
- 所有 `GET/POST/PATCH/DELETE /api/*`

## 常见调用示例

### 1. 创建监控源

```bash
curl -X POST http://127.0.0.1:8000/api/sources \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <your-api-key>" \
  -d '{
    "name": "OpenAI Blog",
    "type": "website",
    "url": "https://openai.com/blog",
    "fetch_interval": 60,
    "enabled": true,
    "priority": 10,
    "extra_urls": [],
    "metadata": {}
  }'
```

### 2. 查询内容列表

```bash
curl -H "X-API-Key: <your-api-key>" \
  "http://127.0.0.1:8000/api/contents?page=1&page_size=50&favorited=false"
```

约束：

- `sources.page_size <= 200`
- `contents.page_size <= 200`

### 3. Reader 正文与按需翻译

```bash
curl -H "X-API-Key: <your-api-key>" \
  "http://127.0.0.1:8000/api/contents/<content-id>/reader?translate=true"
```

流式翻译：

```bash
curl -N -H "X-API-Key: <your-api-key>" \
  "http://127.0.0.1:8000/api/contents/<content-id>/reader/translate-stream"
```

### 4. 指标与健康检查

JSON 指标：

```bash
curl -H "X-API-Key: <your-api-key>" \
  http://127.0.0.1:8000/api/system/metrics
```

Prometheus 指标：

```bash
curl -H "X-API-Key: <your-api-key>" \
  http://127.0.0.1:8000/metrics
```

健康检查：

```bash
curl -H "X-API-Key: <your-api-key>" \
  http://127.0.0.1:8000/health
```

## 认证排查

如果收到 `401 Unauthorized`：

1. 确认请求头使用的是 `X-API-Key`
2. 确认本地 `DATA_DIR/runtime-secrets.json` 或环境变量中的 `PIM_API_KEY` 与客户端一致
3. 可先用 `GET /livez` 验证服务进程是否正常

如果收到 `500 Server misconfigured: API key not set`：

1. 说明服务端未正确加载运行时密钥
2. 重新执行 `./pim setup` 或检查 `DATA_DIR/runtime-secrets.json`
