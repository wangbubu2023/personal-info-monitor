# pimctl 命令参考手册

`pimctl` 是 PIM 的业务 CLI 客户端，所有命令调用后端 API，支持 `--json` 输出供脚本和 Agent 使用。

---

## 全局参数

所有命令均支持以下全局参数，位置在资源名之前：

```bash
pimctl [全局参数] <资源> <命令> [命令参数]
```

| 参数 | 环境变量 | 说明 |
|------|---------|------|
| `--server <url>` | `PIM_SERVER` | API 服务器地址，默认 `http://127.0.0.1:8000` |
| `--api-key <key>` | `PIM_API_KEY` | API 认证密钥 |
| `--profile <name>` | `PIM_PROFILE` | 使用命名 profile（配置文件见 `~/.config/pim/config.toml`） |
| `--json` | — | 输出 JSON 信封格式，Agent 调用必用 |
| `--output <format>` | `PIM_OUTPUT` | 输出格式：`json` / `table` / `text` |
| `--timeout <seconds>` | `PIM_TIMEOUT` | 请求超时，默认 30 秒 |
| `--quiet` | — | 减少非必要输出 |
| `--version` | — | 显示 CLI 版本号 |

**退出码**：`0` 成功 / `1` 通用错误 / `2` 参数错误 / `3` 认证失败 / `4` 资源不存在 / `5` 服务不可达

---

## auth — 认证管理

### `pimctl auth login`

保存服务器地址和 API Key 到本地 profile，并验证连通性。

```bash
pimctl [--server <url>] [--api-key <key>] auth login [--set-default]
```

| 参数 | 说明 |
|------|------|
| `--set-default` | 将此 profile 设为默认 |

```bash
# 示例
pimctl --server http://127.0.0.1:8000 --api-key sk_xxx auth login --set-default
```

---

### `pimctl auth logout`

从当前 profile 删除 API Key（不影响服务端）。

```bash
pimctl auth logout
```

---

### `pimctl auth whoami`

显示当前解析的 profile 信息。

```bash
pimctl auth whoami --json
```

---

## system — 系统状态

### `pimctl system health`

无需认证的存活探针（适合监控系统、load balancer 检查）。

```bash
pimctl system health [--json]
```

```json
{"ok": true, "data": {"status": "ok"}}
```

---

### `pimctl system health-check`

需认证的深度健康检查，验证数据库、调度器、磁盘状态。

```bash
pimctl system health-check [--json]
```

```json
{
  "ok": true,
  "data": {
    "status": "healthy",
    "checks": {
      "database": "ok",
      "scheduler": "ok",
      "disk": "ok"
    },
    "details": {
      "scheduled_jobs": 5,
      "disk_free_bytes": 10737418240
    }
  }
}
```

若任何检查失败，`status` 为 `"degraded"`，HTTP 返回 503（CLI 退出码 1）。

---

### `pimctl system metrics`

运行时指标：请求统计、延迟、任务队列、源级别指标。

```bash
pimctl system metrics [--json]
```

```json
{
  "data": {
    "http": {
      "total_requests": 1024,
      "avg_latency_ms": 12.5,
      "max_latency_ms": 350.0
    },
    "scheduler": {
      "running": true,
      "job_count": 5
    },
    "sources": {
      "<source-id>": {
        "fetch_total": 48,
        "fetch_failures": 1,
        "fetch_avg_ms": 2300.0
      }
    }
  }
}
```

---

### `pimctl system queue`

查看抓取/处理任务队列深度和每个源的当前状态。

```bash
pimctl system queue [--json]
```

---

### `pimctl system stats`

Dashboard 核心统计数字。

```bash
pimctl system stats [--json]
```

```json
{
  "data": {
    "today_total": 142,
    "unread_count": 38,
    "active_sources": 12,
    "favorited_count": 5
  }
}
```

---

### `pimctl system search-rebuild`

手动触发全文搜索索引重建（异步，较慢）。

```bash
pimctl system search-rebuild [--json]
```

---

### `pimctl system doctor`

完整系统诊断，检查数据库、环境、Worker、采集器、第三方集成。

```bash
pimctl system doctor [--json]
```

---

## sources — 监控源管理

### `pimctl sources list`

列出监控源，支持过滤和分页。

```bash
pimctl sources list [--type TYPE] [--enabled true|false] [--search KEYWORD]
                    [--page N] [--page-size N] [--json]
```

| 参数 | 说明 |
|------|------|
| `--type` | `website` / `rss` / `x` / `youtube` / `podcast` |
| `--enabled` | `true` 只看启用的源 |
| `--search` | 按名称搜索 |
| `--page` | 页码，默认 1 |
| `--page-size` | 每页数量，默认 20，最大 200 |

```bash
# 示例
pimctl sources list --type rss --enabled true --json
pimctl sources list --search "OpenAI" --json
```

---

### `pimctl sources get <id>`

获取单个源的完整配置和状态。

```bash
pimctl sources get <source-id> [--json]
```

---

### `pimctl sources add`

创建新监控源。

```bash
pimctl sources add --name NAME --type TYPE --url URL
                   [--extra-url URL ...]    # 可多次传入
                   [--fetch-interval MIN]   # 默认 60 分钟
                   [--disabled]             # 创建时禁用
                   [--auth-required]
                   [--auth-config-id ID]
                   [--json]
```

| 参数 | 说明 |
|------|------|
| `--type` | `website` / `rss` / `x` / `youtube` / `podcast` |
| `--extra-url` | 同一来源的额外 URL，可重复传入 |
| `--fetch-interval` | 抓取间隔（分钟），默认 60 |
| `--disabled` | 创建后不立即启用 |
| `--auth-config-id` | 关联的认证配置 ID |

```bash
# 示例
pimctl sources add \
  --name "Hacker News" \
  --type rss \
  --url "https://news.ycombinator.com/rss" \
  --fetch-interval 30 \
  --json
```

---

### `pimctl sources update <id>`

更新源配置（只更新传入的字段）。

```bash
pimctl sources update <source-id>
                      [--name NAME]
                      [--url URL]
                      [--fetch-interval MIN]
                      [--enabled true|false]
                      [--json]
```

```bash
# 禁用源
pimctl sources update "$id" --enabled false --json

# 更改抓取间隔
pimctl sources update "$id" --fetch-interval 120 --json
```

---

### `pimctl sources delete <id>`

永久删除源及其所有关联内容。

```bash
pimctl sources delete <source-id> [--json]
```

---

### `pimctl sources probe <id>`

重新探测已有源（更新类型识别和 RSS URL 发现），不触发内容抓取。

```bash
pimctl sources probe <source-id> [--json]
```

---

### `pimctl sources probe-url <url>`

探测 URL 的类型和可用性，不创建源。

```bash
pimctl sources probe-url <url> [--type TYPE] [--json]
```

```bash
# 示例：在创建前先探测
pimctl sources probe-url "https://blog.example.com" --json
```

---

### `pimctl sources fetch <id>`

触发对指定源的立即抓取（异步入队，不等待完成）。

```bash
pimctl sources fetch <source-id> [--json]
```

---

### `pimctl sources fetch-all`

触发所有启用源的立即抓取（异步）。

```bash
pimctl sources fetch-all [--json]
```

---

### `pimctl sources export`

导出所有源配置为 JSON，用于备份或迁移。

```bash
pimctl sources export [--json]

# 保存到文件
pimctl sources export --json > sources-backup.json
```

---

## contents — 内容管理

### `pimctl contents list`

列出内容，支持多维度过滤和分页。

```bash
pimctl contents list [--source-id ID] [--source-type TYPE]
                     [--read true|false] [--favorited true|false] [--archived true|false]
                     [--from-date DATETIME] [--to-date DATETIME]
                     [--search KEYWORD]
                     [--page N] [--page-size N]
                     [--json]
```

| 参数 | 说明 |
|------|------|
| `--source-id` | 只看指定源的内容 |
| `--source-type` | `website` / `rss` / `x` / `youtube` / `podcast` |
| `--read` | `false` 只看未读 |
| `--favorited` | `true` 只看收藏 |
| `--archived` | `false` 隐藏归档内容（默认行为） |
| `--from-date` | ISO 8601 格式，如 `2026-04-12T00:00:00` |
| `--to-date` | ISO 8601 格式 |
| `--search` | 全文搜索 |
| `--page-size` | 默认 20，最大 200 |

```bash
# 获取今天未读内容
pimctl contents list \
  --read false \
  --from-date "$(date +%Y-%m-%d)T00:00:00" \
  --page-size 50 \
  --json

# 获取某源的收藏内容
pimctl contents list --source-id "$sid" --favorited true --json
```

---

### `pimctl contents get <id>`

获取单条内容详情（不含完整正文，正文用 `reader` 命令）。

```bash
pimctl contents get <content-id> [--json]
```

---

### `pimctl contents search <query>`

按关键词全文搜索内容。

```bash
pimctl contents search <query> [--page N] [--page-size N] [--json]
```

```bash
pimctl contents search "GPT-5 发布" --json
pimctl contents search "OpenAI" --page-size 50 --json
```

---

### `pimctl contents reader <id>`

获取内容的完整正文（已提取清洁版），支持按需翻译。

```bash
pimctl contents reader <content-id> [--translate] [--json]
```

| 参数 | 说明 |
|------|------|
| `--translate` | 同时请求翻译（调用 AI 翻译，需配置） |

```json
{
  "data": {
    "id": "...",
    "title": "...",
    "translated_title": "...",
    "full_content": "完整正文...",
    "summary": "摘要...",
    "translated_summary": "翻译摘要..."
  }
}
```

---

### `pimctl contents delete <id>`

永久删除单条内容。

```bash
pimctl contents delete <content-id> [--json]
```

---

### `pimctl contents export-md`

触发 Markdown 格式内容导出（异步）。

```bash
pimctl contents export-md [--json]
```

---

### `pimctl contents cleanup-low-signal`

清理低信号网站内容（如无正文的页面）。默认为 dry-run（预览模式）。

```bash
pimctl contents cleanup-low-signal [--apply] [--source-id ID] [--preview-limit N] [--json]
```

| 参数 | 说明 |
|------|------|
| `--apply` | 实际删除（不传则仅预览） |
| `--source-id` | 只处理指定源 |
| `--preview-limit` | 预览条数，默认 20 |

```bash
# 先预览
pimctl contents cleanup-low-signal --json

# 确认后执行
pimctl contents cleanup-low-signal --apply --json
```

---

### `pimctl contents cleanup-junk`

清理垃圾内容（二进制误存为文本、极短的 RSS 条目等）。默认为 dry-run。

```bash
pimctl contents cleanup-junk [--apply] [--source-id ID] [--preview-limit N]
                              [--no-binary] [--no-thin-rss]
                              [--json]
```

| 参数 | 说明 |
|------|------|
| `--apply` | 实际删除 |
| `--no-binary` | 跳过二进制内容检测 |
| `--no-thin-rss` | 跳过极短 RSS 内容检测 |

---

### `pimctl contents mark-read <id>`

标记为已读（幂等）。

```bash
pimctl contents mark-read <content-id> [--json]
```

---

### `pimctl contents mark-unread <id>`

标记为未读（幂等）。

```bash
pimctl contents mark-unread <content-id> [--json]
```

---

### `pimctl contents favorite <id>`

收藏内容（幂等）。

```bash
pimctl contents favorite <content-id> [--json]
```

---

### `pimctl contents unfavorite <id>`

取消收藏（幂等）。

```bash
pimctl contents unfavorite <content-id> [--json]
```

---

### `pimctl contents archive <id>`

归档内容（幂等）。

```bash
pimctl contents archive <content-id> [--json]
```

---

### `pimctl contents unarchive <id>`

取消归档（幂等）。

```bash
pimctl contents unarchive <content-id> [--json]
```

---

## keywords — 关键词监控

### `pimctl keywords list`

列出所有关键词。

```bash
pimctl keywords list [--enabled true|false] [--json]
```

```json
{
  "data": {
    "items": [
      {
        "id": "...",
        "keyword": "OpenAI",
        "match_type": "contains",
        "match_scope": "title_content",
        "enabled": true,
        "notify": false,
        "notify_email": true,
        "color": "#ef4444"
      }
    ],
    "total": 1
  }
}
```

---

### `pimctl keywords get <id>`

获取单个关键词详情。

```bash
pimctl keywords get <keyword-id> [--json]
```

---

### `pimctl keywords add <keyword>`

创建关键词监控。

```bash
pimctl keywords add <keyword>
                    [--match-type contains|exact|regex]  # 默认 contains
                    [--match-scope title|content|title_content]  # 默认 title_content
                    [--description TEXT]
                    [--color HEX]         # 默认 #3b82f6
                    [--case-sensitive]
                    [--notify]            # 应用内通知
                    [--notify-email]      # 邮件告警
                    [--disabled]
                    [--json]
```

```bash
# 简单添加
pimctl keywords add "Claude" --json

# 完整配置
pimctl keywords add "GPT-5" \
  --match-type contains \
  --match-scope title \
  --color "#ef4444" \
  --notify-email \
  --json

# 正则匹配
pimctl keywords add "GPT-\d+" \
  --match-type regex \
  --match-scope title_content \
  --json
```

---

### `pimctl keywords batch-add <kw1> [<kw2> ...]`

批量创建关键词，共享相同配置。重复的关键词自动跳过（不报错）。

```bash
pimctl keywords batch-add <keyword1> <keyword2> ...
                           [--match-type ...]
                           [--match-scope ...]
                           [--notify] [--notify-email]
                           [--color HEX]
                           [--disabled]
                           [--json]
```

```bash
pimctl keywords batch-add \
  "OpenAI" "Anthropic" "Google DeepMind" "Meta AI" \
  --match-scope title \
  --notify \
  --color "#8b5cf6" \
  --json
```

返回：

```json
{
  "data": {
    "total": 3,
    "skipped_keywords": ["OpenAI"]
  }
}
```

---

### `pimctl keywords update <id>`

更新关键词配置（只更新传入的字段）。

```bash
pimctl keywords update <keyword-id>
                       [--match-type ...]
                       [--match-scope ...]
                       [--description TEXT]
                       [--color HEX]
                       [--case-sensitive true|false]
                       [--notify true|false]
                       [--notify-email true|false]
                       [--enabled true|false]
                       [--json]
```

```bash
# 禁用关键词
pimctl keywords update "$kid" --enabled false --json

# 开启邮件告警
pimctl keywords update "$kid" --notify-email true --json
```

---

### `pimctl keywords batch-update <id1> [<id2> ...]`

批量更新多个关键词的共享字段。

```bash
pimctl keywords batch-update <id1> <id2> ...
                              [--enabled true|false]
                              [--notify true|false]
                              [--notify-email true|false]
                              [--color HEX]
                              [--match-type ...]
                              [--match-scope ...]
                              [--json]
```

```bash
# 批量启用
pimctl keywords batch-update "$id1" "$id2" "$id3" --enabled true --json

# 批量关闭邮件告警
pimctl keywords batch-update $(pimctl keywords list --json | jq -r '.data.items[].id') \
  --notify-email false --json
```

---

### `pimctl keywords delete <id>`

删除关键词（同时清除内容中已保存的命中记录）。

```bash
pimctl keywords delete <keyword-id> [--json]
```

---

## settings — 系统设置

### `pimctl settings get`

获取完整系统设置。

```bash
pimctl settings get [--json]
```

---

### `pimctl settings limits`

仅获取运行时限制配置（源数量上限、摘要候选数等）。

```bash
pimctl settings limits [--json]
```

---

### `pimctl settings set`

修改单个配置项，自动推断类型（bool / int / string）。

```bash
pimctl settings set --key <key> --value <value> [--json]
```

```bash
# 暂停所有 AI 处理（恢复时设为 false）
pimctl settings set --key ai_processing_paused --value true --json

# 修改最大源数量
pimctl settings set --key max_sources --value 100 --json
```

---

## digest — 摘要报告

### `pimctl digest latest`

获取今日日报（按来源类型分组）。

```bash
pimctl digest latest [--json]
```

---

### `pimctl digest stats`

获取最近 N 天的内容统计（每日数量、类型分布、未读/收藏数）。

```bash
pimctl digest stats [--json]
```

```json
{
  "data": {
    "period": {"start": "2026-04-06", "end": "2026-04-12", "days": 7},
    "daily_counts": [
      {"date": "2026-04-12", "count": 142}
    ],
    "type_counts": {"rss": 89, "website": 35, "x": 18},
    "unread_count": 38,
    "favorited_count": 5
  }
}
```

---

### `pimctl digest hourly-list`

列出可用的小时报（最近 24 小时）。

```bash
pimctl digest hourly-list [--date YYYY-MM-DD] [--json]
```

```json
{
  "data": [
    {"hour": "2026-04-12T15", "item_count": 12, "generated_at": "..."},
    {"hour": "2026-04-12T14", "item_count": 8, "generated_at": "..."}
  ]
}
```

---

### `pimctl digest day <date>`

获取指定日期的日报。

```bash
pimctl digest day <YYYY-MM-DD> [--json]
```

```bash
pimctl digest day 2026-04-12 --json
```

---

### `pimctl digest hour <hour>`

获取指定小时的详细摘要。

```bash
pimctl digest hour <YYYY-MM-DDTHH> [--json]
```

```bash
pimctl digest hour 2026-04-12T15 --json
```

---

## 使用示例汇总

### 快速健康检查

```bash
pimctl system health --json && echo "PIM is alive"
```

### 获取最新未读内容标题

```bash
pimctl contents list --read false --page-size 10 --json | \
  jq -r '.data.items[] | "\(.publish_time[:10]) \(.title)"'
```

### 添加并立即抓取一个 RSS 源

```bash
id=$(pimctl sources add --name "Test" --type rss \
  --url "https://example.com/feed" --json | jq -r '.data.id')
pimctl sources fetch "$id" --json
```

### 搜索内容并标记已读

```bash
pimctl contents search "关键词" --json | \
  jq -r '.data.items[].id' | \
  xargs -I{} pimctl contents mark-read {} --json > /dev/null
```

### 查看所有命中关键词的内容

```bash
pimctl contents list --read false --json | \
  jq '.data.items[] | select(.keyword_matches | length > 0) | {title, keywords: [.keyword_matches[].keyword]}'
```

### 批量添加监控源并等待抓取完成

```bash
urls=("https://blog.a.com" "https://blog.b.com" "https://feeds.c.com/rss")
for url in "${urls[@]}"; do
  pimctl sources add --name "${url##*/}" --type website --url "$url" --json > /dev/null
done

pimctl sources fetch-all --json

# 等待队列清空
while [ "$(pimctl system queue --json | jq '.data.running_fetches')" -gt 0 ]; do
  sleep 5
done
echo "Done"
```

---

## atoms — 新闻原子库

> `main` 分支暂时不注册 `atoms` 命令；以下命令保留给 `dev` 分支的原子库实验使用。

> 需 `ATOMS_ENABLED=true`。默认关闭时 API 返回 404。

### `pimctl atoms list`

```bash
pimctl atoms list [--type 信息|观点|数据] [--domain 科技] [--verified true|false]
                  [--atom-source 路透] [--content-id <uuid>] [--search <关键词>]
                  [--page 1] [--page-size 20] [--json]
```

### `pimctl atoms stats`

```bash
pimctl atoms stats [--json]
```

### `pimctl atoms get`

```bash
pimctl atoms get <atom_id> [--json]
```

### `pimctl atoms verify`

```bash
pimctl atoms verify <atom_id> [--json]
```

### `pimctl atoms atomize`

单篇重新 LLM 提取：

```bash
pimctl atoms atomize <content_id> [--json]
```

### `pimctl atoms backfill`

历史文章批量提取（异步 job）：

```bash
pimctl atoms backfill [--limit 500] [--since 2026-01-01] [--content-id <uuid>] [--dry-run] [--json]
```

### `pimctl atoms backfill-status`

```bash
pimctl atoms backfill-status <job_id> [--json]
```

### `pimctl atoms relations list`

> 需 `ATOMS_RELATIONS_ENABLED=true`（且 `ATOMS_ENABLED=true`）。

```bash
pimctl atoms relations list [--atom-id <id>] [--verified true|false]
                          [--page 1] [--page-size 20] [--json]
```

### `pimctl atoms relations reconcile`

全库或增量重跑跨文关系推断（异步 job，可能耗时较长）：

```bash
pimctl atoms relations reconcile [--limit 1000] [--since 2026-01-01]
                                 [--atom-id <id>] [--dry-run] [--json]
```

### `pimctl atoms relations reconcile-status`

```bash
pimctl atoms relations reconcile-status <job_id> [--json]
```

### `pimctl atoms relations verify`

确认印证关系，并联动两端原子 `fact_confidence` +0.05：

```bash
pimctl atoms relations verify <rel_id> [--json]
```
