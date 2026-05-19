# PIM 审计报告修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复代码审计报告中第一阶段的所有阻断性问题，使前端测试重新通过、消除已知安全漏洞、统一 Digest 时间口径。

**Architecture:** 共四项独立修复：(1) 升级高危依赖 axios；(2) 修复前端单测与 feature flag 不一致；(3) 移除 VITE_PIM_API_KEY 注入路径；(4) 统一 Digest 查询时间字段并将 func.date() 改为范围查询以利用索引。

**Tech Stack:** Python/FastAPI (backend), React/TypeScript/Vitest (frontend), SQLAlchemy, npm

---

### Task 1: 升级 axios 到安全版本

**Files:**

- Modify: `frontend/package.json:26`
- **Step 1: 将 axios 版本从 ^1.6.5 改为 ^1.14.0**

Edit `frontend/package.json` line 26:

```json
"axios": "^1.14.0",
```

- **Step 2: 安装更新后的依赖**

```bash
cd frontend && npm install
```

Expected: npm install 完成，无报错

- **Step 3: 验证漏洞已修复**

```bash
cd frontend && npm audit --omit=dev
```

Expected: `found 0 vulnerabilities`

- **Step 4: 运行 lint 确保无回归**

```bash
cd frontend && npm run lint
```

Expected: 无警告无错误

---

### Task 2: 修复前端 Settings 测试与 feature flag 不一致

**Files:**

- Modify: `frontend/src/components/Settings/Settings.test.tsx:19-29`

**问题：** `features.ts` 中 `KEYWORD_MONITORING_ENABLED = true`，导致 Settings 渲染了"搜索词管理"标签，但测试第 27 行断言 `not.toContain('搜索词管理')`，造成测试失败。

**修复方案：** 在测试中通过 `vi.mock` 显式 mock `features` 模块，将 `KEYWORD_MONITORING_ENABLED` 设为 `false`，让测试明确验证"关闭 flag 时不渲染该标签"的行为。

- **Step 1: 更新测试文件，添加 features mock**

将 `frontend/src/components/Settings/Settings.test.tsx` 修改为：

```tsx
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../../config/features', () => ({
  PODCAST_SOURCES_ENABLED: false,
  KEYWORD_MONITORING_ENABLED: false,
}))

vi.mock('../SourceList/SourceManager', () => ({
  default: () => React.createElement('div', { 'data-testid': 'mock-source-manager' }, 'Source Manager'),
}))

vi.mock('./APIKeysTab', () => ({
  default: () => React.createElement('div', null, 'API Keys'),
}))

vi.mock('./AIModelTab', () => ({
  default: () => React.createElement('div', null, 'AI Model'),
}))

import Settings from './Settings'

describe('Settings', () => {
  it('renders the settings header and default tabs', () => {
    const html = renderToStaticMarkup(React.createElement(Settings))

    expect(html).toContain('设置')
    expect(html).toContain('监控源管理')
    expect(html).toContain('采集凭证')
    expect(html).toContain('模型管理')
    expect(html).not.toContain('搜索词管理')
    expect(html).toContain('settings-page')
  })
})
```

- **Step 2: 运行前端测试验证修复**

```bash
cd frontend && npm test
```

Expected: `15 passed | 0 failed`

---

### Task 3: 移除 VITE_PIM_API_KEY 注入路径

**Files:**

- Modify: `pim:363-364`
- Modify: `frontend/src/services/apiKeyStore.ts:32-58`

**问题：** `pim` 脚本在开发启动时把 API Key 注入为 `VITE_PIM_API_KEY` 环境变量，`apiKeyStore.ts` 再把它写入 `localStorage`/`sessionStorage`，导致共享 API Key 在浏览器调试环境可见。

- **Step 1: 移除 pim 脚本中的 VITE_PIM_API_KEY 注入**

在 `pim` 文件中删除第 363-364 行：

```python
            if api_key:
                frontend_env.setdefault("VITE_PIM_API_KEY", api_key)
```

保留其余 `frontend_env` 配置（`VITE_API_URL`、`PIM_DEV_HOST`）。

- **Step 2: 移除 apiKeyStore.ts 中的 getBundledApiKey 函数及其调用**

在 `frontend/src/services/apiKeyStore.ts` 中：

1. 删除整个 `getBundledApiKey` 函数（第 32-34 行）
2. 在 `readApiKey` 函数中删除 bundled key 的读取与写入逻辑（第 48-58 行），即删除：

```ts
  const bundledValue = getBundledApiKey()

  if (bundledValue) {
    if (persistentStorage?.getItem(WEB_LOCAL_KEY) !== bundledValue) {
      persistentStorage?.setItem(WEB_LOCAL_KEY, bundledValue)
    }
    if (sessionStorageRef?.getItem(WEB_SESSION_KEY) !== bundledValue) {
      sessionStorageRef?.setItem(WEB_SESSION_KEY, bundledValue)
    }
    return bundledValue
  }
```

- **Step 3: 验证 lint 和测试无回归**

```bash
cd frontend && npm run lint && npm test
```

Expected: lint 通过，所有测试通过

---

### Task 4: 统一 Digest 时间口径并改为范围查询

**Files:**

- Modify: `backend/app/api/digest.py:57-61,143-165`
- Modify: `backend/app/services/digest_service.py:44-50,141-155`

**问题：**

- `digest.py` API 用 `fetched_at` 过滤，`digest_service.py` 用 `publish_time` 过滤 → UI/邮件 digest 结果不一致
- 两处都用 `func.date(...)` 包装字段，抵消了 `ix_content_fetched_at`/`ix_content_publish_time` 索引

**统一策略：** 以 `fetched_at` 为标准字段（"何时抓到"比"何时发布"更可控），并将日期过滤改为 UTC 范围查询（`>= day_start` 且 `< next_day_start`）。

- **Step 1: 在 digest.py 中修复每日 digest 的日期过滤**

在 `backend/app/api/digest.py` 的 `get_daily_digest` 函数中，将：

```python
.filter(func.date(Content.fetched_at) == target_date)
```

替换为：

```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
_TZ = ZoneInfo("Asia/Shanghai")
day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=_TZ).astimezone(timezone.utc).replace(tzinfo=None)
day_end = day_start + timedelta(days=1)
```

并将 query filter 改为：

```python
.filter(Content.fetched_at >= day_start, Content.fetched_at < day_end)
```

注意：`timedelta` 已在文件顶部 import，无需重复导入；`SYSTEM_TZ` 已定义在模块级，使用它替代局部 `_TZ`。

- **Step 2: 在 digest.py 中修复 stats 的日期范围查询**

在 `get_digest_stats` 函数中，先将 `start_date`/`end_date` 转换为 UTC 时间戳：

```python
from zoneinfo import ZoneInfo
stats_start_utc = datetime(start_date.year, start_date.month, start_date.day, tzinfo=SYSTEM_TZ).astimezone(timezone.utc).replace(tzinfo=None)
stats_end_utc = datetime(end_date.year, end_date.month, end_date.day, tzinfo=SYSTEM_TZ).astimezone(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
```

然后将所有 `func.date(Content.fetched_at) >= start_date` 和 `func.date(Content.fetched_at) <= end_date` 改为：

```python
Content.fetched_at >= stats_start_utc, Content.fetched_at < stats_end_utc
```

- **Step 3: 在 digest_service.py 中统一为 fetched_at 字段**

在 `DigestService.generate_daily_digest` 中，将：

```python
.filter(func.date(Content.publish_time) == date)
```

替换为（添加 import datetime 和 timezone/timedelta）：

```python
from datetime import timezone, timedelta
from zoneinfo import ZoneInfo
_SYSTEM_TZ = ZoneInfo("Asia/Shanghai")
day_start = datetime(date.year, date.month, date.day, tzinfo=_SYSTEM_TZ).astimezone(timezone.utc).replace(tzinfo=None)
day_end = day_start + timedelta(days=1)
```

并将 filter 改为：

```python
.filter(Content.fetched_at >= day_start, Content.fetched_at < day_end)
```

同时在 `get_weekly_summary` 中，将所有 `func.date(Content.publish_time)` 的日期过滤也改为 `fetched_at` 范围查询。

- **Step 4: 运行后端测试验证无回归**

```bash
cd backend && ./.venv/bin/pytest -q 2>&1 | tail -5
```

Expected: `556 passed` 或类似通过数量，无新失败

---

