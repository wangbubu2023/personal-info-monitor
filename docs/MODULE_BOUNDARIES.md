# PIM 模块边界（一页纸）

> 完整迁移步骤见 [MODULE_REFACTOR_PLAN.md](./MODULE_REFACTOR_PLAN.md)。  
> ADR：[ADR-005-module-boundaries.md](./ADR-005-module-boundaries.md)

## 三层结构

```
交付层    interfaces/http · cli/pimctl · frontend · ./pim
领域层    domains/sources · fetch · ingest · atoms · enrich  （五个）
平台层    platform/auth · config · workers · observability · …
```

## 五模块

| 模块 | 目录 | 做什么 | 不做什么 |
|------|------|--------|----------|
| **信源** | `domains/sources` | CRUD、探测、何时该抓、状态展示 | 抓网页、写 Content、LLM |
| **抓取** | `domains/fetch` | 拉原始条目、认证、锁与限速 | 去重入库、摘要、原子化 |
| **预处理** | `domains/ingest` | 清洗、去重、入库、FTS、关键词、质量分 | 对外 HTTP、LLM、简报 |
| **新闻原子** | `domains/atoms` | 结构化事件/实体（可选功能） | 抓取、用户可读文案 |
| **增强** | `domains/enrich` | 摘要、翻译、Reader、日报/小时报、邮件内容 | 信源配置、collector |

## 数据流

```
sources → fetch → ingest → [atoms] → enrich
                      ↑         ↑
                   必选      可选（enrich L1 回退 Content）
```

## 依赖（禁止）

- `fetch` → `enrich` / `atoms`
- `ingest` → LLM
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
| `fetch` | 抓取 |
| `ingest` | 预处理 |
| `atoms` | 结构化 |
| `enrich` | 摘要/翻译/简报 |

## 配置分组（`.env`）

- `FETCH_*` → fetch  
- `ATOMS_*` → atoms（默认关）  
- `ENRICH_*` → enrich（替代 `AI_PROCESSING_ENABLED`）  
