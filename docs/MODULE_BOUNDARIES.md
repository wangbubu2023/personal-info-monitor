# PIM 模块边界（一页纸）

> 完整目录注解见 [PROJECT_STRUCTURE.md](./PROJECT_STRUCTURE.md)；架构总览见
> [ARCHITECTURE.md](./ARCHITECTURE.md)；边界门禁见
> `backend/scripts/check_domain_imports.py`。

## 三层结构

```
交付层    interfaces/http · cli/pimctl · frontend · ./pim
领域层    domains/sources · fetch · ingest · score · atoms · enrich  （六个）
平台层    platform/auth · config · workers · observability · …
```

## 六模块 + 七阶段

**领域模块（6）**

| 模块 | 目录 | 做什么 | 不做什么 |
|------|------|--------|----------|
| **信源** | `domains/sources` | CRUD、探测、何时该抓、状态展示 | 抓网页、写 Content、LLM |
| **抓取** | `domains/fetch` | 拉原始条目、**正文二跳**、**验收**、认证、锁与限速 | 去重入库、LLM、打分、原子化 |
| **预处理** | `domains/ingest` | 清洗、去重、入库、FTS、关键词 | 对外 HTTP、LLM、打分、简报 |
| **评分** | `domains/score` | pim-score-v2 单篇分、selection、事件层词表 | 抓取、LLM、入库、简报 |
| **新闻原子** | `domains/atoms` | 归一化 A/B/C 事实原子、跨文关系（可选） | 抓取、用户可读文案 |
| **增强** | `domains/enrich` | LLM 摘要阶段、listing 翻译、Reader、日报/小时报 | 信源配置、collector、打分 |

**流水线阶段（7）** — 由 `ingest/finish.py` 编排：

```
sources → fetch → ingest → summarize → score → [atoms] → enrich
```

| 阶段 | 实现位置 | 交付物 |
|------|----------|--------|
| fetch（含二跳+验收） | `fetch/finalize` · `fetch/acceptance` | 完整原始内容（`fetch_acceptance=accepted`） |
| ingest | `ingest/summary_clean` · 关键词 | 干净正文 + listing 摘要（extractive） |
| summarize | `enrich/content/summarize` | canonical summary（LLM，可选） |
| score | `score/scoring` | `article_score` / `selection_status`（读**原文** title/summary） |
| atoms | `atoms/` | 结构化原子（可选） |
| enrich | `enrich/content/listing_translation` · reader · digest | 中文 listing、全文翻译、简报 |

## 依赖（禁止）

- `fetch`（`acceptance` / `article_body` / `finalize`）→ `ingest` / `score` / `enrich` / `atoms`
- `ingest` → LLM
- `score` → `enrich` / LLM
- `domains` → `interfaces`
- `pimctl` → `app.domains`

## 交付入口

| 入口 | 类型 | 说明 |
|------|------|------|
| `/api/*` | HTTP | 薄路由，调 domains |
| `pimctl` | CLI | 仅 HTTP，独立包 `cli/` |
| `./pim` | 运维 | venv、启停、备份，不 import domains |
| 前端 | UI | 同 API |

## 排障

| 日志 `domain=` | 模块 |
|----------------|------|
| `sources` | 信源/调度 |
| `fetch` | 抓取 / 二跳 / 验收 |
| `ingest` | 预处理 |
| `score` | 评分 |
| `atoms` | 结构化 |
| `enrich` | 摘要 / 翻译 / 简报 |

## 配置分组（`.env`）

- `FETCH_*` → fetch
- `ATOMS_ENABLED` → 新闻原子库开关，默认 `false`
- `ATOMS_RELATIONS_ENABLED` → 跨文关系推断（P2），依赖 `ATOMS_ENABLED`
- system settings 中的 AI 产品开关 → 自动摘要、列表翻译、主观评分与全局暂停
- `PIM_AI_HARD_DISABLE` → 部署级 LLM 紧急停机开关
- `AI_PROCESSING_ENABLED` / `ENRICH_*` → 仅用于旧安装首次升级默认值迁移

校验：`backend/scripts/check_domain_imports.py --phase=7` 会在 CI 中静态强制依赖方向。
