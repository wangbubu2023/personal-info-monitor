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

暴露的核心系列（全部为 `counter` 或 `gauge`，适合直接在 Grafana / Prometheus 中查询）：

- `pim_http_requests_total` — 累计 HTTP 请求数（counter）
- `pim_http_requests_by_status{status="2xx|3xx|4xx|5xx"}` — 按状态码分桶（counter）
- `pim_http_requests_by_route{route="METHOD /path"}` — 按路由分桶（counter）
- `pim_http_request_latency_ms_total` — 累计请求延迟（counter；用于平均延迟）
- `pim_http_request_latency_ms_max` — 进程内最大单次延迟（gauge）
- `pim_tasks_dropped_total{task_type="fetch|process"}` — 因队列满被丢弃的任务（counter）

**`rate()` 推荐查询**

Counter 在进程重启时会保留累计值（由后端 `data_dir/metrics-checkpoint.json` 持久化，优雅停机时写入，启动时读取），因此 `rate()` 在绝大多数场景下都能得到有意义的结果：

```promql
# 过去 5 分钟 QPS
rate(pim_http_requests_total[5m])

# 按状态码拆分的 5xx 错误率
sum by (status) (rate(pim_http_requests_by_status[5m]))

# 按路由的 Top-10 QPS
topk(10, rate(pim_http_requests_by_route[5m]))

# 平均延迟（毫秒）= 累计延迟 / 累计请求数
rate(pim_http_request_latency_ms_total[5m])
  / clamp_min(rate(pim_http_requests_total[5m]), 1)

# 任务丢弃频率（健康时应为 0）
rate(pim_tasks_dropped_total[5m])
```

注意事项：

- 使用 5m/1m 时间窗口时，Prometheus 抓取周期建议 ≤15s，以保证至少两个样本。
- 重启期间会有一次采样间隔的"空洞"，`rate()` 会自动平滑这个间隙。
- JSON 端点 `/api/system/metrics` 返回的是快照而非时间序列，适合仪表盘实时展示，不适合做速率计算。

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
