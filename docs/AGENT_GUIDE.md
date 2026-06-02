# PIM Agent 集成指南

本文档面向通过 `pimctl` CLI 调用 PIM 的 Agent 系统（如 OpenClaw、自定义 AI Agent、脚本自动化）。

---

## 目录

1. [环境准备](#1-环境准备)
2. [认证配置](#2-认证配置)
3. [调用规范](#3-调用规范)
4. [核心工作流](#4-核心工作流)
5. [错误处理](#5-错误处理)
6. [Agent 典型场景](#6-agent-典型场景)
7. [性能与并发](#7-性能与并发)
8. [安全边界](#8-安全边界)

---

## 1. 环境准备

### 1.1 在 VPS 上安装 PIM

```bash
git clone <仓库地址> personal-info-monitor
cd personal-info-monitor
./pim setup
```

作为 systemd 服务运行（见 [VPS_DEPLOY.md](VPS_DEPLOY.md) 完整配置）：

```bash
# 服务配置 /etc/systemd/system/pim.service
[Service]
WorkingDirectory=/path/to/personal-info-monitor
ExecStart=/path/to/personal-info-monitor/pim up --foreground --server
Environment=TRUSTED_PROXY_IPS=127.0.0.1  # 若使用反向代理
Restart=always

sudo systemctl enable --now pim
```

无 systemd 的容器环境中，让平台 HEARTBEAT、cron 或守护脚本反复调用：

```bash
cd /path/to/personal-info-monitor
./pim ensure --server
```

该命令健康时无操作；进程缺失或 `/livez` 不返回 HTTP 200 时会拉起/重启；8000
端口被非 PIM 进程占用时会失败退出，避免双启。

### 1.2 安装 pimctl

`pimctl` 是 PIM 的 CLI 客户端，与服务端同仓库：

```bash
# 在项目根目录，将 pimctl 加入 PATH
export PATH="$PATH:/path/to/personal-info-monitor"

# 或创建符号链接
ln -s /path/to/personal-info-monitor/pimctl /usr/local/bin/pimctl
```

验证安装：

```bash
pimctl --version
```

### 1.3 验证服务就绪

```bash
# 无需认证的存活探针
pimctl system health --json
# → {"ok": true, "data": {"status": "ok"}, ...}

# 认证后的深度健康检查
pimctl system health-check --json
# → {"ok": true, "data": {"status": "healthy", "checks": {"database": "ok", "scheduler": "ok", "disk": "ok"}}, ...}
```

---

## 2. 认证配置

### 2.1 认证方式（按优先级）


| 方式                                     | 适用场景                                         |
| -------------------------------------- | -------------------------------------------- |
| CLI 参数 `--api-key`                     | 单次调用，脚本内临时使用                                 |
| 环境变量 `PIM_API_KEY`                     | Agent 进程级配置，推荐                               |
| profile 文件 `~/.config/pim/config.toml` | 多环境管理                                        |
| 本地自动发现                                 | 同机调用，自动读取 `~/.pim/data/runtime-secrets.json` |


### 2.2 推荐：环境变量方式

Agent 启动时注入环境变量，所有 pimctl 调用自动携带：

```bash
export PIM_SERVER=http://127.0.0.1:8000   # 或 https://pim.yourdomain.com
export PIM_API_KEY=<your-api-key>

# 之后所有调用无需再传 --api-key
pimctl sources list --json
```

获取 API Key：

```bash
# 同机部署，直接读取
cat ~/.pim/data/runtime-secrets.json | python3 -c "import sys,json; print(json.load(sys.stdin)['PIM_API_KEY'])"
```

### 2.3 Profile 配置（多环境）

适合 Agent 同时管理多个 PIM 实例：

```toml
# ~/.config/pim/config.toml
default_profile = "prod"

[profiles.local]
server = "http://127.0.0.1:8000"
api_key = "local-key-xxx"
output = "json"
timeout = 30

[profiles.prod]
server = "https://pim.yourdomain.com"
api_key = "prod-key-yyy"
output = "json"
timeout = 60
```

```bash
# 初次设置 profile
pimctl --server http://127.0.0.1:8000 --api-key <key> auth login --set-default

# 切换 profile
pimctl --profile local sources list --json
pimctl --profile prod sources list --json
```

---

## 3. 调用规范

### 3.1 输出格式

**所有 Agent 调用都应使用 `--json`**，确保输出结构稳定可解析。

**成功响应结构**：

```json
{
  "ok": true,
  "data": { },
  "error": null,
  "meta": {
    "server": "http://127.0.0.1:8000",
    "cli_version": "1.2.2",
    "profile": "local"
  }
}
```

**失败响应结构**：

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "not_found",
    "message": "Resource not found"
  },
  "meta": { ... }
}
```

**解析示例**：

```bash
result=$(pimctl sources list --json)
ok=$(echo "$result" | jq -r '.ok')
if [ "$ok" = "true" ]; then
    echo "$result" | jq '.data.items[]'
fi
```

```python
import subprocess, json

def pimctl(*args):
    result = subprocess.run(
        ["pimctl", "--json"] + list(args),
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    if not data["ok"]:
        raise RuntimeError(f"pimctl error: {data['error']['code']} — {data['error']['message']}")
    return data["data"]

sources = pimctl("sources", "list")
```

### 3.2 退出码


| 退出码 | 含义    | Agent 处理建议            |
| --- | ----- | --------------------- |
| `0` | 成功    | 解析 stdout JSON        |
| `1` | 通用错误  | 记录日志，检查 `error.code`  |
| `2` | 参数错误  | 修复调用方式                |
| `3` | 认证失败  | 检查 `PIM_API_KEY` 是否过期 |
| `4` | 资源不存在 | 正常情况，跳过处理             |
| `5` | 服务不可达 | 重试，或告警                |


### 3.3 超时配置

```bash
# 全局超时
export PIM_TIMEOUT=60

# 单次调用
pimctl --timeout 120 sources fetch-all --json
```

长任务建议超时值：


| 操作     | 建议超时    |
| ------ | ------- |
| 普通查询   | 30s（默认） |
| 触发抓取   | 60s     |
| 系统诊断   | 120s    |
| 搜索索引重建 | 300s    |


---

## 4. 核心工作流

### 4.1 订阅新内容源

```bash
# 1. 先探测 URL，确认类型和可用性
pimctl sources probe-url "https://openai.com/blog" --json

# 2. 创建源
pimctl sources add \
  --name "OpenAI Blog" \
  --type website \
  --url "https://openai.com/blog" \
  --fetch-interval 60 \
  --json

# 3. 立即触发首次抓取
source_id=$(pimctl sources list --search "OpenAI Blog" --json | jq -r '.data.items[0].id')
pimctl sources fetch "$source_id" --json
```

### 4.2 添加关键词监控

```bash
# 添加单个关键词（命中时发邮件告警）
pimctl keywords add "GPT-5" \
  --match-type contains \
  --match-scope title_content \
  --notify-email \
  --color "#ef4444" \
  --json

# 批量添加同类关键词
pimctl keywords batch-add \
  "OpenAI" "Anthropic" "Google Gemini" "Meta Llama" \
  --match-scope title \
  --notify \
  --json
```

### 4.3 获取最新内容

```bash
# 获取最近未读内容（最新 20 条）
pimctl contents list --read false --page-size 20 --json

# 搜索特定话题
pimctl contents search "大模型 融资" --json

# 获取某个源的最新内容
pimctl contents list \
  --source-id "$source_id" \
  --read false \
  --json | jq '.data.items[] | {title, original_url, publish_time}'

# 获取今天抓取的内容
pimctl contents list \
  --from-date "$(date +%Y-%m-%d)T00:00:00" \
  --json
```

### 4.4 读取内容全文

```bash
content_id="<uuid>"

# 获取正文（自动提取，去广告）
pimctl contents reader "$content_id" --json | jq '.data.full_content'

# 获取正文并翻译
pimctl contents reader "$content_id" --translate --json | \
  jq '{title: .data.translated_title, summary: .data.translated_summary}'
```

### 4.5 获取摘要报告

```bash
# 今日日报（按来源分类）
pimctl digest latest --json

# 指定日期
pimctl digest day "2026-04-12" --json

# 最近一小时摘要（适合高频轮询）
pimctl digest hourly-list --json | jq '.data[0]'  # 最新小时

# 最近 7 天统计
pimctl digest stats --json | jq '{
  unread: .data.unread_count,
  daily: .data.daily_counts
}'
```

### 4.6 系统状态监控

```bash
# 快速存活检查（无需认证）
pimctl system health --json

# 深度健康检查
pimctl system health-check --json | jq '.data.checks'

# 查看抓取队列状态
pimctl system queue --json | jq '{
  fetching: .data.running_fetches,
  processing: .data.running_processes
}'

# 请求统计
pimctl system metrics --json | jq '.data.http'
```

---

## 5. 错误处理

### 5.1 错误码处理模式

```python
import subprocess, json, time, logging

def pimctl_call(*args, retries=3, backoff=5):
    """带重试的 pimctl 调用"""
    for attempt in range(retries):
        result = subprocess.run(
            ["pimctl", "--json"] + list(args),
            capture_output=True, text=True, timeout=60
        )
        
        if result.returncode == 0:
            return json.loads(result.stdout)["data"]
        
        data = json.loads(result.stdout) if result.stdout else {}
        error_code = (data.get("error") or {}).get("code", "unknown")
        
        # 不可重试的错误
        if result.returncode in (2, 3):  # 参数错误、认证失败
            raise RuntimeError(f"Fatal: {error_code}")
        
        if result.returncode == 4:  # 资源不存在
            return None
        
        # 可重试的错误（服务不可达、超时）
        if attempt < retries - 1:
            logging.warning(f"Attempt {attempt+1} failed ({error_code}), retrying in {backoff}s...")
            time.sleep(backoff)
            backoff *= 2
    
    raise RuntimeError(f"pimctl failed after {retries} attempts")
```

### 5.2 常见错误及处理


| 错误码                  | 原因            | 处理方式                  |
| -------------------- | ------------- | --------------------- |
| `auth_failed`        | API Key 无效或过期 | 检查 `PIM_API_KEY` 环境变量 |
| `not_found`          | 资源 ID 不存在     | 跳过，继续处理其他资源           |
| `server_unreachable` | 服务未启动或网络问题    | 等待后重试，触发告警            |
| `timeout`            | 请求超时          | 增大 `--timeout` 值      |
| `conflict`           | 重复创建（如同名源）    | 检查是否已存在               |
| `bad_request`        | 参数格式错误        | 检查调用参数                |


### 5.3 幂等操作说明

以下操作支持重复调用（结果相同）：

- `sources fetch <id>` — 触发抓取，重复调用不会重复入库
- `contents mark-read <id>` — 多次标记已读无副作用
- `contents favorite <id>` — 多次调用结果一致
- `sources add` — 同 URL 会返回 409 Conflict，不会重复创建

---

## 6. Agent 典型场景

### 6.1 每日内容摘要 Agent

```bash
#!/bin/bash
# daily_digest.sh — 适合 cron 每天运行

set -e
PIM_SERVER="http://127.0.0.1:8000"
PIM_API_KEY="$(cat ~/.pim/data/runtime-secrets.json | python3 -c "import sys,json; print(json.load(sys.stdin)['PIM_API_KEY'])")"
export PIM_SERVER PIM_API_KEY

# 获取昨天日期
DATE=$(date -d "yesterday" +%Y-%m-%d 2>/dev/null || date -v-1d +%Y-%m-%d)

# 获取日报
pimctl digest day "$DATE" --json > /tmp/pim_digest.json

# 检查是否有内容
total=$(jq '[.data.categories[].count] | add // 0' /tmp/pim_digest.json)
echo "Yesterday: $total items across all sources"

# 输出关键词命中内容
pimctl contents list \
  --from-date "${DATE}T00:00:00" \
  --to-date "${DATE}T23:59:59" \
  --json | \
  jq '.data.items[] | select(.keyword_matches | length > 0) | {title, url: .original_url, keywords: [.keyword_matches[].keyword]}'
```

### 6.2 实时监控 Agent（轮询模式）

```python
# monitor_agent.py — 每 5 分钟检查新内容
import subprocess, json, time
from datetime import datetime, timedelta

def pimctl(*args):
    r = subprocess.run(["pimctl", "--json"] + list(args), 
                       capture_output=True, text=True, timeout=30)
    d = json.loads(r.stdout)
    return d["data"] if d["ok"] else None

last_check = datetime.utcnow() - timedelta(minutes=5)

while True:
    # 获取最新小时摘要
    hourly = pimctl("digest", "hourly-list")
    if hourly and len(hourly) > 0:
        latest_hour = hourly[0]
        print(f"Latest hour: {latest_hour['hour']} — {latest_hour['item_count']} items")
    
    # 获取新的关键词命中内容
    from_ts = last_check.strftime("%Y-%m-%dT%H:%M:%S")
    contents = pimctl("contents", "list",
                      "--from-date", from_ts,
                      "--page-size", "50")
    
    if contents:
        keyword_hits = [c for c in contents.get("items", []) 
                        if c.get("keyword_matches")]
        for item in keyword_hits:
            keywords = [m["keyword"] for m in item["keyword_matches"]]
            print(f"[ALERT] {item['title']} — keywords: {keywords}")
    
    last_check = datetime.utcnow()
    time.sleep(300)  # 5 分钟
```

### 6.3 批量配置 Agent（初始化新实例）

```bash
#!/bin/bash
# setup_monitoring.sh — 为新 PIM 实例批量配置监控
export PIM_API_KEY=$(cat ~/.pim/data/runtime-secrets.json | python3 -c "import sys,json; print(json.load(sys.stdin)['PIM_API_KEY'])")

# 批量添加 RSS 源
RSS_FEEDS=(
  "Hacker News|https://news.ycombinator.com/rss|rss|30"
  "OpenAI Blog|https://openai.com/blog|website|60"
  "Anthropic News|https://www.anthropic.com/news|website|120"
)

for entry in "${RSS_FEEDS[@]}"; do
  IFS="|" read -r name url type interval <<< "$entry"
  result=$(pimctl sources add \
    --name "$name" \
    --type "$type" \
    --url "$url" \
    --fetch-interval "$interval" \
    --json 2>&1)
  
  ok=$(echo "$result" | jq -r '.ok')
  if [ "$ok" = "true" ]; then
    echo "Added: $name"
  else
    code=$(echo "$result" | jq -r '.error.code')
    echo "Skipped $name: $code"
  fi
done

# 批量添加关键词
pimctl keywords batch-add \
  "AGI" "OpenAI" "Anthropic" "Gemini" "Claude" "GPT" \
  --match-scope title_content \
  --notify \
  --color "#3b82f6" \
  --json

echo "Setup complete"
pimctl system stats --json | jq '{sources: .data.active_sources}'
```

### 6.4 内容处理 Agent（读取→分析→标记）

```python
# content_processor.py — 读取内容、处理后标记已读
import subprocess, json

def pimctl(*args):
    r = subprocess.run(["pimctl", "--json"] + list(args),
                       capture_output=True, text=True)
    d = json.loads(r.stdout)
    return d["data"] if d["ok"] else None

def process_content(content_id: str) -> str:
    """读取全文，返回 AI 分析结果（示意）"""
    data = pimctl("contents", "reader", content_id, "--translate")
    if not data:
        return ""
    return data.get("translated_summary") or data.get("summary") or ""

# 获取未读内容
unread = pimctl("contents", "list", "--read", "false", "--page-size", "20")
if not unread:
    exit()

for item in unread["items"]:
    cid = item["id"]
    title = item["title"]
    
    # 处理关键词命中的内容
    if item.get("keyword_matches"):
        summary = process_content(cid)
        print(f"[KW HIT] {title}\n  {summary[:200]}\n")
    
    # 标记已读
    pimctl("contents", "mark-read", cid)

print(f"Processed {len(unread['items'])} items")
```

---

## 7. 性能与并发

### 7.1 请求频率建议

PIM 默认限速 **120 请求/分钟/IP**，Agent 调用时注意：


| 操作     | 建议频率         |
| ------ | ------------ |
| 内容列表查询 | ≤ 1 次/5 秒    |
| 触发抓取   | ≤ 1 次/30 秒/源 |
| 关键词管理  | 无特殊限制        |
| 系统健康检查 | ≤ 1 次/分钟     |


### 7.2 批量操作优先于循环

```bash
# 不推荐：循环单个删除（N 次请求）
for id in $ids; do pimctl contents mark-read "$id" --json; done

# 推荐：使用后端提供的批量 API（如有）
# 对于标记已读，可先 list 过滤，再处理
pimctl contents list --read false --page-size 200 --json | \
  jq -r '.data.items[].id' | \
  while read id; do pimctl contents mark-read "$id" --json > /dev/null; done
```

### 7.3 抓取任务是异步的

`pimctl sources fetch <id>` 只是入队，不会等待抓取完成。

若需等待结果：

```bash
pimctl sources fetch "$source_id" --json

# 轮询队列直到空闲
while true; do
  queue=$(pimctl system queue --json | jq '.data.running_fetches')
  [ "$queue" -eq 0 ] && break
  echo "Still fetching ($queue tasks)..."
  sleep 5
done
```

---

## 8. 安全边界

### 8.1 pimctl 不能做的事

- 不能执行任意系统命令
- 不能直接读写数据库
- 不能绕过 PIM 的认证层
- 不能访问非 PIM API 的任意 HTTP 端点

### 8.2 API Key 保护

```bash
# 正确：通过环境变量传递
export PIM_API_KEY=xxx
pimctl sources list --json

# 错误：在命令行直接传递（会记录到 shell history）
pimctl --api-key xxx sources list --json

# 清除 history 中的敏感信息
history -d $(history | tail -1 | awk '{print $1}')
```

### 8.3 Agent 权限原则

- Agent 应使用 **只读账号**（若将来 PIM 支持权限分级）
- 当前版本所有操作共享同一 API Key，Agent 理论上可以执行所有写操作
- 建议在 Agent 代码层面限制危险操作（如 `sources delete`、`contents cleanup-junk --apply`）

### 8.4 SSRF 保护

PIM 内部已对所有外部 URL 抓取进行 SSRF 检查，Agent 提供的 URL 不会被用于访问内网资源。

---

## 附录：快速参考

完整命令参考见 [PIMCTL_REFERENCE.md](PIMCTL_REFERENCE.md)。

**最常用的 Agent 命令**：

```bash
# 健康检查
pimctl system health --json
pimctl system health-check --json

# 内容获取
pimctl contents list --read false --page-size 50 --json
pimctl contents search "关键词" --json
pimctl contents reader <id> --translate --json

# 关键词
pimctl keywords list --json
pimctl keywords add "term" --notify-email --json
pimctl keywords batch-add term1 term2 --json

# 源管理
pimctl sources list --json
pimctl sources fetch <id> --json
pimctl sources fetch-all --json

# 摘要
pimctl digest latest --json
pimctl digest hourly-list --json
pimctl digest stats --json
```
