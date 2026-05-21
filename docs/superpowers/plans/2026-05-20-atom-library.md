# 新闻原子库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Phase 6 的 Bundle 占位层升级为归一化新闻原子库（A/B/C 三类事实原子 + P2 跨文 D 类关系），支持 LLM 提取、人工验证前端、数据存于 `~/.pim/data/pim.db`。

**Architecture:** 一步到位弃用 `content_atom_bundles`，新建 `atoms` + `atom_relations` 表；Pydantic  discriminated union 做类型校验；ingest 完成后 sidecar 调用 LLM 提取器 upsert 原子；P2 异步 worker 做跨文关系推断。与 Obsidian 无任何集成。

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy / Alembic / Pydantic v2 / pytest；React + TanStack Query + Tailwind（前端）；`ModelProviderClient`（LLM）。

**已锁定设计决策：** 见本文「设计决策摘要」。

---

## 设计决策摘要

| 项 | 决策 |
|----|------|
| 存储 | 归一化 `atoms` + `atom_relations`；删除 `content_atom_bundles` |
| atom_type | 一 atom 一 type；一句可拆多条 |
| who | A/B 统一 `[{name, type}]`；B 类额外 `role` |
| 信源 | `atom_source`（原子级陈述来源）；`source_credibility` 绑 atom_source |
| 重提取 | atom_id **稳定**：按 `(content_id, source_sentence, atom_type)` 匹配 upsert；`verified=true` 的不自动删除 |
| 跨文 P2 | 仅跨文章；同 domain + 共享 entity + 时间窗；首批 信息/数据；relation 印证+矛盾；规则筛候选+LLM 判型 |
| 印证 verified | 联动两端 `fact_confidence` +0.05（封顶 1.0） |
| 数据位置 | `~/.pim/data/pim.db`；Obsidian 无关 |

---

## 目标架构

```
ingest.finish_content
       │
       ▼ (ATOMS_ENABLED=true)
atomize_content(content_id)
       │
       ├─ sentence_split(full_content)
       ├─ llm_extract(sentences) → Info/Opinion/Data atoms
       ├─ validate + credibility map
       └─ repository.upsert_for_content()  # 稳定 atom_id

P2 (ATOMS_RELATIONS_ENABLED=true)
       │
       ▼ 新原子入库后 enqueue
relation_infer_worker(atom_id)
       ├─ find_candidates(domain, entities, time)
       ├─ llm_judge_relation_type
       └─ relations.upsert (verified=false)

Frontend /atoms
       ├─ GET  列表/筛选/分页
       ├─ PATCH 人工修正 + verified
       └─ P2: 关系确认/拒绝/手动新建
```

---

## 文件结构（新建/修改）

### Backend — 新建

| 文件 | 职责 |
|------|------|
| `backend/app/domains/atoms/vocab.py` | 16 套 StrEnum / Literal |
| `backend/app/domains/atoms/types.py` | Pydantic：WhoEntry、InfoAtomPayload、OpinionAtomPayload、DataAtomPayload、AtomCreate/AtomRead |
| `backend/app/domains/atoms/id_gen.py` | `ATOM-{YYYYMMDD}-{seq}` / `REL-{YYYYMMDD}-{seq}` |
| `backend/app/domains/atoms/credibility.py` | atom_source 名称 → 默认分值映射表 |
| `backend/app/domains/atoms/repository.py` | SqlAtomRepository（重写） |
| `backend/app/domains/atoms/relations_repository.py` | SqlAtomRelationRepository（P2） |
| `backend/app/domains/atoms/extractor/sentence_split.py` | 中文/英文句子切分 |
| `backend/app/domains/atoms/extractor/llm_extract.py` | LLM prompt + JSON 解析 |
| `backend/app/domains/atoms/extractor/validate.py` | Pydantic 校验 + source_sentence 原文校验 |
| `backend/app/domains/atoms/extractor/upsert.py` | 按 content 批量 upsert + 孤儿清理 |
| `backend/app/domains/atoms/relation_infer/candidates.py` | P2 候选对筛选 |
| `backend/app/domains/atoms/relation_infer/llm_judge.py` | P2 LLM 判 relation_type |
| `backend/app/domains/atoms/relation_infer/worker.py` | P2 异步推断入口 |
| `backend/app/models/atom.py` | 重写：`Atom`、`AtomRelation` ORM |
| `backend/app/schemas/atom.py` | HTTP 请求/响应 schema |
| `backend/app/interfaces/http/atoms.py` | REST 路由 |
| `backend/alembic/versions/20260520_0014_atoms_normalized.py` | migration |
| `backend/tests/test_atoms_vocab.py` | 词表 |
| `backend/tests/test_atoms_types.py` | Pydantic round-trip |
| `backend/tests/test_atoms_repository.py` | CRUD + upsert 稳定性 |
| `backend/tests/test_atoms_extractor.py` | 切分/校验/mock LLM |
| `backend/tests/test_atoms_api.py` | HTTP 集成 |
| `backend/tests/test_atoms_relations.py` | P2 |

### Backend — 修改

| 文件 | 变更 |
|------|------|
| `backend/app/domains/atoms/atomizer.py` | 调用 extractor + upsert；移除 heuristic bundle 逻辑 |
| `backend/app/domains/atoms/schema.py` | schema_version=2；废弃 bundle 转换 |
| `backend/app/domains/contracts/atoms.py` | 新 contract：`AtomRecord`、`AtomReader.get_atoms_for_content` |
| `backend/app/domains/atoms/__init__.py` | 更新 exports |
| `backend/app/features.py` | 新增 `ATOMS_RELATIONS_ENABLED`（P2，默认 false） |
| `backend/app/interfaces/http/__init__.py` | 注册 atoms router（gated by ATOMS_ENABLED） |
| `backend/app/models/__init__.py` | 导出 Atom/AtomRelation；移除 ContentAtomBundle |
| `backend/tests/test_atoms_layer.py` | 重写为归一化模型测试 |

### Frontend — 新建

| 文件 | 职责 |
|------|------|
| `frontend/src/types/atoms.ts` | TS 类型 |
| `frontend/src/services/atoms.ts` | API client |
| `frontend/src/pages/AtomsPage.tsx` | 原子库主页 |
| `frontend/src/components/Atoms/AtomFilters.tsx` | type/domain/verified/搜索 |
| `frontend/src/components/Atoms/AtomList.tsx` | 表格/卡片列表 |
| `frontend/src/components/Atoms/AtomDetailDrawer.tsx` | 详情 + 跳转原文 |
| `frontend/src/components/Atoms/AtomEditForm.tsx` | 按 type 动态表单 |
| `frontend/src/components/Atoms/AtomRelationsPanel.tsx` | P2 关系展示/操作 |

### Frontend — 修改

| 文件 | 变更 |
|------|------|
| `frontend/src/App.tsx` | 路由 `/atoms` |
| `frontend/src/components/layout/MainLayout.tsx` | 侧栏「原子库」入口（feature flag） |
| `frontend/src/config/features.ts` | `ATOMS_ENABLED` 前端开关 |
| `frontend/src/services/queryKeys.ts` | atoms query keys |

---

## 数据库 Schema（P0）

### `atoms`

```sql
CREATE TABLE atoms (
    atom_id          VARCHAR(32) PRIMARY KEY,   -- ATOM-20260520-00142
    content_id       UUID NOT NULL REFERENCES contents(id) ON DELETE CASCADE,
    atom_type        VARCHAR(16) NOT NULL,      -- 信息|观点|数据
    domain           VARCHAR(32) NOT NULL,
    source_sentence  TEXT NOT NULL,
    source_url       TEXT NOT NULL,
    atom_source      VARCHAR(255) NOT NULL,
    payload          JSON NOT NULL,             -- type-specific fields
    verified         BOOLEAN NOT NULL DEFAULT FALSE,
    source_credibility REAL NOT NULL,
    fact_confidence  REAL NOT NULL,
    schema_version   INTEGER NOT NULL DEFAULT 2,
    created_at       TIMESTAMP NOT NULL,
    updated_at       TIMESTAMP NOT NULL,
    UNIQUE(content_id, source_sentence, atom_type)
);
CREATE INDEX ix_atoms_content_id ON atoms(content_id);
CREATE INDEX ix_atoms_atom_type ON atoms(atom_type);
CREATE INDEX ix_atoms_domain ON atoms(domain);
CREATE INDEX ix_atoms_verified ON atoms(verified);
CREATE INDEX ix_atoms_created_at ON atoms(created_at);
```

### `atom_relations`（P0 建表，P2 写数据）

```sql
CREATE TABLE atom_relations (
    rel_id           VARCHAR(32) PRIMARY KEY,   -- REL-20260520-00021
    atom_a           VARCHAR(32) NOT NULL REFERENCES atoms(atom_id) ON DELETE CASCADE,
    atom_b           VARCHAR(32) NOT NULL REFERENCES atoms(atom_id) ON DELETE CASCADE,
    relation_type    VARCHAR(16) NOT NULL,
    direction        VARCHAR(8) NOT NULL,       -- A→B|B→A|双向
    verified         BOOLEAN NOT NULL DEFAULT FALSE,
    fact_confidence  REAL NOT NULL,
    created_at       TIMESTAMP NOT NULL,
    updated_at       TIMESTAMP NOT NULL,
    UNIQUE(atom_a, atom_b)
);
CREATE INDEX ix_atom_relations_atom_a ON atom_relations(atom_a);
CREATE INDEX ix_atom_relations_atom_b ON atom_relations(atom_b);
```

### `atom_id_sequences`（日序号）

```sql
CREATE TABLE atom_id_sequences (
    prefix     VARCHAR(16) PRIMARY KEY,  -- ATOM-20260520 / REL-20260520
    last_seq   INTEGER NOT NULL DEFAULT 0
);
```

### Migration 收尾

- `DROP TABLE content_atom_bundles`（现有 heuristic 数据可丢弃）
- 删除 `backend/alembic/versions/20260520_0013_create_content_atom_bundles.py` 的反向兼容无需保留

---

## Phase P0 — 基础层（预计 3–4 天）

> 交付标准：无 LLM 也可手工 POST 原子；前端可浏览/编辑/verified；测试全绿。

### Task P0-1: 词表与 Pydantic 类型

**Files:**
- Create: `backend/app/domains/atoms/vocab.py`
- Create: `backend/app/domains/atoms/types.py`
- Create: `backend/tests/test_atoms_vocab.py`
- Create: `backend/tests/test_atoms_types.py`

- [ ] **Step 1:** 在 `vocab.py` 定义 StrEnum：`AtomType`（信息/观点/数据）、`Domain`（11 值）、`WhatType`、`Validity`、`Role`、`Sentiment`、`Intensity`、`SourceType`、`Unit`、`PeriodType`、`RelationType`、`Direction`、`SubjectType`（词表5）
- [ ] **Step 2:** 在 `types.py` 定义 `WhoEntry(name, type: SubjectType)`；三个 payload 模型 + 公共字段 mixin
- [ ] **Step 3:** 写 round-trip 测试（文档中三个 JSON 示例必须通过校验）
- [ ] **Step 4:** `pytest backend/tests/test_atoms_vocab.py backend/tests/test_atoms_types.py -v`

### Task P0-2: ORM + Migration

**Files:**
- Rewrite: `backend/app/models/atom.py`
- Create: `backend/alembic/versions/20260520_0014_atoms_normalized.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1:** 实现 `Atom`、`AtomRelation`、`AtomIdSequence` ORM
- [ ] **Step 2:** Alembic upgrade：建三表 + drop `content_atom_bundles`
- [ ] **Step 3:** 本地 `./pim db migrate` 验证

### Task P0-3: ID 生成器

**Files:**
- Create: `backend/app/domains/atoms/id_gen.py`
- Test: `backend/tests/test_atoms_repository.py`（id 部分）

- [ ] **Step 1:** `next_atom_id(session) -> str` 事务内 `SELECT ... FOR UPDATE` 或 SQLite 等价 upsert 递增
- [ ] **Step 2:** `next_rel_id(session) -> str` 同理
- [ ] **Step 3:** 测试同日并发递增不重复（单进程 sequential 测试即可）

### Task P0-4: Repository

**Files:**
- Rewrite: `backend/app/domains/atoms/repository.py`
- Create: `backend/tests/test_atoms_repository.py`

- [ ] **Step 1:** `create_atom` / `get_atom` / `list_atoms(filters, page, page_size)` / `update_atom`
- [ ] **Step 2:** `upsert_atoms_for_content(content_id, atoms[])` — 匹配键 `(content_id, source_sentence, atom_type)`；保留 atom_id 与 verified；删除 unmatched 且 verified=false 的旧原子
- [ ] **Step 3:** `list_atoms` 支持筛选：atom_type, domain, verified, atom_source, entity 关键词（JSON payload 内 entities 字段 LIKE）
- [ ] **Step 4:** pytest 覆盖 upsert 稳定性（同 content 重跑 id 不变）

### Task P0-5: Credibility 映射

**Files:**
- Create: `backend/app/domains/atoms/credibility.py`
- Test: 同上

- [ ] **Step 1:** `DEFAULT_SOURCE_CREDIBILITY: dict[str, float]` — 路透/新华社/财新/匿名等（按设计文档词表3 区间取中值）
- [ ] **Step 2:** `resolve_credibility(atom_source: str) -> float` — exact match → 模糊 contains → 默认 0.55
- [ ] **Step 3:** 单元测试 5 个典型来源

### Task P0-6: HTTP API

**Files:**
- Create: `backend/app/schemas/atom.py`
- Create: `backend/app/interfaces/http/atoms.py`
- Modify: `backend/app/interfaces/http/__init__.py`
- Create: `backend/tests/test_atoms_api.py`

- [ ] **Step 1:** 路由（均需 API key）：
  - `GET /atoms` — 列表+筛选+分页
  - `GET /atoms/{atom_id}`
  - `PATCH /atoms/{atom_id}` — 人工修正；可设 verified
  - `POST /atoms` — 手工录入（运维/测试用）
  - `POST /contents/{content_id}/atomize` — 手动触发提取（P1 后可用）
- [ ] **Step 2:** router 仅在 `atoms_enabled()` 时注册（或返回 404）
- [ ] **Step 3:** API 集成测试

### Task P0-7: 更新 Contract + 废弃 Bundle

**Files:**
- Modify: `backend/app/domains/contracts/atoms.py`
- Modify: `backend/app/domains/atoms/schema.py`
- Rewrite: `backend/tests/test_atoms_layer.py`

- [ ] **Step 1:** 新 `AtomRecord` frozen dataclass；`AtomReader.get_atoms_for_content(content_id) -> tuple[AtomRecord, ...]`
- [ ] **Step 2:** `SqlAtomReader` 改读 `atoms` 表；移除 `AtomBundle` / `get_bundle`（或 deprecate 一版）
- [ ] **Step 3:** `CURRENT_SCHEMA_VERSION = 2`
- [ ] **Step 4:** 更新 Phase 6 测试

### Task P0-8: 前端原子库页面

**Files:** 见 Frontend 新建列表 + App/MainLayout/features

- [ ] **Step 1:** `services/atoms.ts` + `types/atoms.ts`
- [ ] **Step 2:** `AtomsPage` — 顶栏筛选（type/domain/verified/搜索）+ 分页列表
- [ ] **Step 3:** `AtomDetailDrawer` — 展示 source_sentence、atom_source、confidence；链接 `source_url` / Reader
- [ ] **Step 4:** `AtomEditForm` — 按 atom_type 渲染字段；保存 PATCH；「标记已验证」按钮
- [ ] **Step 5:** 侧栏入口 + 路由；`ATOMS_ENABLED` false 时隐藏
- [ ] **Step 6:** 手动冒烟：启动 stack → 打开 `/atoms` → PATCH 一条

### P0 验收清单

- [ ] `./pim test backend` 全绿
- [ ] migration 在空库和已有 Phase 6 库均可跑通
- [ ] 前端可筛选、编辑、verified
- [ ] `ATOMS_ENABLED=false` 时 API 不可用、前端入口隐藏

---

## Phase P1 — LLM 提取（预计 4–5 天）

> 交付标准：新入库文章自动生成 A/B/C 原子；source_sentence 原文校验；失败不阻塞 ingest。

### Task P1-1: 句子切分

**Files:**
- Create: `backend/app/domains/atoms/extractor/sentence_split.py`
- Test: `backend/tests/test_atoms_extractor.py`

- [ ] **Step 1:** 中文：`。！？；` + 换行；英文：`.!?`；保留索引映射回原文
- [ ] **Step 2:** 过滤空句、过短句（< 8 字符）
- [ ] **Step 3:** 单元测试混合中英文段落

### Task P1-2: LLM Prompt 与解析

**Files:**
- Create: `backend/app/domains/atoms/extractor/llm_extract.py`
- Create: `backend/app/domains/atoms/extractor/validate.py`

- [ ] **Step 1:** Prompt 模板 — 输入句子 batch（≤15 句/call）；输出 JSON array；每元素含 atom_type + 字段 + atom_source + fact_confidence
- [ ] **Step 2:** System prompt 嵌入词表 enum 合法值；要求 source_sentence 逐字 copy
- [ ] **Step 3:** `parse_llm_response(text) -> list[AtomCreate]` — json.loads + Pydantic
- [ ] **Step 4:** `assert_sentence_in_source(source_sentence, full_content)` — 子串校验，失败丢弃该条
- [ ] **Step 5:** Mock LLM 测试（patch `ModelProviderClient.generate_text`）

### Task P1-3: 提取管线整合

**Files:**
- Create: `backend/app/domains/atoms/extractor/upsert.py`
- Rewrite: `backend/app/domains/atoms/atomizer.py`

- [ ] **Step 1:** `extract_atoms_from_content(content: Content) -> list[AtomCreate]`
  - 取 `full_content` 或 fallback `summary`
  - 无正文 → 空列表（不报错）
- [ ] **Step 2:** `atomize_content` 调用 extract → upsert；metadata 记录 extractor_version、llm_model、sentence_count、atom_count
- [ ] **Step 3:** 异常 swallow + log（保持 Phase 6 不变量）
- [ ] **Step 4:** 集成测试：seed content → atomize → 查 atoms 表

### Task P1-4: pimctl atoms 命令组 + 回填 API

**Files:**
- Modify: `cli/pimctl/app.py` — `_build_atoms_parser` + handlers
- Modify: `backend/app/interfaces/http/atoms.py` — 回填/job 端点
- Test: `backend/tests/test_atoms_api.py`（backfill job）

- [ ] **Step 1:** 后端 `POST /atoms/backfill` — body: `{limit, since, content_id?}`；返回 `{job_id}`；后台 asyncio task 分批 atomize
- [ ] **Step 2:** 后端 `GET /atoms/backfill/{job_id}` — `{status, processed, total, errors}`
- [ ] **Step 3:** pimctl 命令（均支持 `--json`）见下文「CLI 能力清单」
- [ ] **Step 4:** flag 关闭时 pimctl 打印明确错误（HTTP 404 → 退出码 4）

### Task P1-5: 前端增强

- [ ] **Step 1:** 列表展示 atom_source、fact_confidence 进度条
- [ ] **Step 2:** Content/Reader 页可选「查看原子(N)」跳转 `/atoms?content_id=...`
- [ ] **Step 3:** 手动触发「重新提取」按钮 → `POST /contents/{id}/atomize`

### P1 验收清单

- [ ] 真实文章提取 ≥3 篇人工 spot-check：source_sentence 可定位、type 合理
- [ ] 重跑 atomize 同 content：atom_id 稳定、verified 保留
- [ ] ingest 主路径 LLM 失败时仍正常完成

---

## Phase P2 — 跨文关系（预计 3–4 天）

> 交付标准：新数据/信息原子入库后自动产生印证/矛盾候选；前端可确认/拒绝/手建关系。

### Task P2-0: Feature Flag

**Files:**
- Modify: `backend/app/features.py`

- [ ] **Step 1:** `ATOMS_RELATIONS_ENABLED` 默认 false；依赖 `ATOMS_ENABLED`

### Task P2-1: Relations Repository

**Files:**
- Create: `backend/app/domains/atoms/relations_repository.py`
- Test: `backend/tests/test_atoms_relations.py`

- [ ] **Step 1:** `upsert_relation` — UNIQUE(atom_a, atom_b)；verified=true 不覆盖
- [ ] **Step 2:** `list_relations_for_atom(atom_id)`
- [ ] **Step 3:** `delete_relation(rel_id)`；级联由 FK 处理
- [ ] **Step 4:** `apply_verified_corroboration(rel_id)` — verified 印证 → 两端 confidence +0.05 cap 1.0

### Task P2-2: 候选筛选

**Files:**
- Create: `backend/app/domains/atoms/relation_infer/candidates.py`

- [ ] **Step 1:** `find_candidates(atom: Atom) -> list[Atom]`
  - 跨 content_id
  - 同 domain
  - entities 交集 ≥1（payload.entities 或 who names）
  - 时间：when/period 差 ≤30 天 OR 同一 period 字符串
  - atom_type ∈ {信息, 数据}
  - 上限 50 候选
- [ ] **Step 2:** 单元测试用 fixture 原子

### Task P2-3: LLM 关系判定

**Files:**
- Create: `backend/app/domains/atoms/relation_infer/llm_judge.py`

- [ ] **Step 1:** 输入 atom_a + atom_b 关键字段；输出 relation_type ∈ {印证, 矛盾} 或 null
- [ ] **Step 2:** direction：印证→双向；矛盾→按语义
- [ ] **Step 3:** fact_confidence 写入 relation 行
- [ ] **Step 4:** Mock 测试

### Task P2-4: 异步 Worker

**Files:**
- Create: `backend/app/domains/atoms/relation_infer/worker.py`
- Modify: `backend/app/domains/atoms/extractor/upsert.py`（enqueue hook）
- Modify: `backend/app/platform/workers/queue.py` 或 BackgroundTasks

- [ ] **Step 1:** 新原子 upsert 后若 `ATOMS_RELATIONS_ENABLED` → enqueue `infer_relations(atom_id)`
- [ ] **Step 2:** 每个 atom 最多写入 5 条新关系
- [ ] **Step 3:** 可选：`pimctl atoms relations-reconcile` 夜间 batch

### Task P2-5: Relations HTTP API

**Files:**
- Modify: `backend/app/interfaces/http/atoms.py`

- [ ] **Step 1:**
  - `GET /atoms/{atom_id}/relations`
  - `PATCH /atom-relations/{rel_id}` — verified / relation_type
  - `POST /atom-relations` — 手动创建
  - `DELETE /atom-relations/{rel_id}`

### Task P2-6: 前端关系面板

**Files:**
- Create: `frontend/src/components/Atoms/AtomRelationsPanel.tsx`

- [ ] **Step 1:** 详情 drawer 内「关联原子」Tab
- [ ] **Step 2:** 印证/矛盾视觉区分；矛盾并排对比 source_sentence
- [ ] **Step 3:** 确认/拒绝按钮；手动添加关系表单

### P2 验收清单

- [ ] 同一事件两篇报道 → 产生印证关系
- [ ] 冲突数据 → 矛盾关系 + UI 并排
- [ ] verified 印证后 confidence 上调
- [ ] verified 关系不被重推断覆盖

---

## Phase P3 — Enrich 集成（可选，预计 2 天）

> 非阻塞；可在 P1 稳定后做。

- [ ] **Task P3-1:** 小时报选稿 — 含未 verified 数据原子的 content 加权
- [ ] **Task P3-2:** 综述素材 — synthesis prompt 注入结构化 `what`/`metric`
- [ ] **Task P3-3:** `enrich` 仅通过 `AtomReader` port 读取，不 import atoms ORM

---

## 测试策略

| 层 | 覆盖 |
|----|------|
| 单元 | vocab、types、credibility、sentence_split、validate、candidates |
| 集成 | repository upsert 稳定性、API CRUD |
| Mock LLM | extractor、relation judge — 不依赖真实 API |
| E2E 可选 | Playwright：`/atoms` 列表+编辑 |

运行：`cd backend && pytest tests/test_atoms_*.py -v`

---

## 上线与运维

1. **Flag 顺序：** 部署代码 → `ATOMS_ENABLED=true` → 观察提取 → `ATOMS_RELATIONS_ENABLED=true`
2. **回填：** `pimctl atoms backfill --limit 500` 分批跑，监控 LLM 配额
3. **监控：** log 字段 `domain=atoms`；metrics：atomize_success/fail、atoms_per_content、relations_created
4. **回滚：** flag 置 false 即可；表保留无害

---

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| LLM 输出不符合 schema | Pydantic 校验 + 最多 1 次 retry；失败句跳过 |
| source_sentence 幻觉 | 子串校验；不在原文则丢弃 |
| 跨文关系误判 | 首批仅印证/矛盾；默认 verified=false；人工页确认 |
| 重提取断关系 | atom_id 稳定 + verified 原子不删；关系 FK cascade 仅删 atom 时触发 |
| SQLite JSON 查询慢 | 初期数据量小可接受；后续可加 entity 倒排表 |

---

## 建议实施顺序（甘特）

```
Week 1:  P0-1 → P0-7（后端完整）+ P0-8 列表页
Week 2:  P0-8 编辑完善 + P1-1 → P1-3（LLM 提取）
Week 3:  P1-4/P1-5 + P2-0 → P2-6（跨文关系）
Week 4:  回填生产数据 + P3 可选 + 文档更新
```

---

## CLI 能力清单

### 分工原则

| 工具 | 职责 | 原子库相关 |
|------|------|-----------|
| **`pimctl`** | 业务操作，**只调 HTTP API**（模块边界 ADR-005） | **主要 CLI 入口** — 查询、触发提取、回填、关系统计 |
| **`./pim`** | 本地运维：启停、迁移、备份、日志 | **不新增 atoms 业务命令**；仅 env 模板、status 展示 flag、备份已含 atoms 表 |

理由：回填/关系 reconcile 可能跑数小时，必须走服务端 job + API；`pimctl` 与 Agent 集成路径一致；`./pim` 保持「不 import domains」。

### pimctl — `atoms` 资源（P0 起）

```bash
pimctl atoms list [--type 信息|观点|数据] [--domain 科技] [--verified true|false]
                  [--atom-source 路透] [--content-id <uuid>] [--search <关键词>]
                  [--page 1] [--page-size 20] [--json]

pimctl atoms get <atom_id> [--json]

pimctl atoms stats [--json]
# → {total, by_type, by_domain, verified_count, unverified_count, last_24h}

pimctl atoms atomize <content_id> [--json]
# → POST /contents/{id}/atomize；单篇重新提取

pimctl atoms verify <atom_id> [--json]
# → PATCH verified=true 快捷命令
```

### pimctl — P1 追加

```bash
pimctl atoms backfill [--limit 500] [--since 2026-01-01] [--content-id <uuid>]
                      [--dry-run] [--json]
# → POST /atoms/backfill；轮询 job 直到 done 或 --quiet 只打印 job_id

pimctl atoms backfill-status <job_id> [--json]
```

### pimctl — P2 追加

```bash
pimctl atoms relations list [--atom-id <id>] [--verified true|false] [--json]

pimctl atoms relations reconcile [--limit 1000] [--since 2026-01-01] [--json]
# → POST /atoms/relations/reconcile；全库或增量重跑关系推断

pimctl atoms relations verify <rel_id> [--json]
```

### pimctl 实现 Task

**Files:**
- Modify: `cli/pimctl/app.py`
- Optional: `cli/pimctl/atoms_handlers.py`（parser 过长时拆分）

- [ ] **P0:** `list` / `get` / `stats` / `verify` / `atomize`
- [ ] **P1:** `backfill` + `backfill-status`（带进度条 text 模式）
- [ ] **P2:** `relations list` / `reconcile` / `verify`
- [ ] 所有 handler 复用 `APIClient`；table 模式列：atom_id, type, domain, atom_source, verified, what/say_what/metric 摘要

### ./pim — 最小变更

**Files:**
- Modify: `backend/.env.example`
- Modify: `pim` — `status` 子命令可选读取 `.env` 打印 feature flags
- Modify: `pim` 文件头 docstring

- [ ] **Step 1:** `.env.example` 增加：
  ```bash
  # 新闻原子库（默认关闭）
  ATOMS_ENABLED=false
  ATOMS_RELATIONS_ENABLED=false
  ```
- [ ] **Step 2:** `./pim status` 增加一行：`atoms: off|on (extract)  relations: off|on`
- [ ] **Step 3:** **不**在 `./pim` 加 backfill——避免绕过 API、超时、与 pimctl 重复

### system health-check 扩展（P1）

**Files:**
- Modify: `backend/app/interfaces/http/system.py`

- [ ] `health-check` 的 `details` 增加（当 `ATOMS_ENABLED`）：
  ```json
  "atoms": {"enabled": true, "total": 1240, "unverified": 890, "last_atomize_at": "..."}
  ```

便于 `pimctl system health-check --json` 一眼看到原子库状态。

---

## 运维文档最终更新清单

> **触发时机：** P0 完成后写「启用/浏览」；P1 完成后写「提取/回填」；P2 完成后写「关系」；全部完成后做一次总审。

### 必改文档（按文件）

| 文件 | Phase | 新增内容 |
|------|-------|----------|
| **`docs/PIMCTL_REFERENCE.md`** | P0/P1/P2 | 新章 `## atoms — 新闻原子库`：全部 pimctl 子命令、JSON 示例、退出码说明 |
| **`docs/USER_GUIDE.md`** | P0/P1 | 新章「新闻原子库」：侧栏入口、`/atoms` 页面用法、verified 工作流、与 Reader 跳转；注明需 `ATOMS_ENABLED=true` |
| **`docs/TROUBLESHOOTING.md`** | P1/P2 | 新节「原子库」：提取为空、LLM 失败、backfill 慢、关系过多、flag 开了但无数据 |
| **`docs/AGENT_GUIDE.md`** | P1 | §4 加工作流「查询结构化原子」；§6 加场景「按 domain 拉取未验证数据原子」 |
| **`docs/MODULE_BOUNDARIES.md`** | P0 | atoms 职责改为「A/B/C 事实原子 + D 跨文关系」；数据流图 `[atoms]` 标注 |
| **`docs/ARCHITECTURE.md`** | P0/P1 | atoms 域架构图；`atoms`/`atom_relations` 表；sidecar 提取时序 |
| **`docs/PROJECT_STRUCTURE.md`** | P0 | 附录 B `pim.db` 表清单加 `atoms`、`atom_relations`、`atom_id_sequences` |
| **`backend/README.md`** | P0 | Feature flags、`domains/atoms/` 目录说明 |
| **`backend/.env.example`** | P0 | `ATOMS_ENABLED`、`ATOMS_RELATIONS_ENABLED` |
| **`docs/VPS_DEPLOY.md`** | P1 | 启用 atoms 的 env 示例；LLM 配额提醒；backfill 建议低峰执行 |
| **`docs/USER_GUIDE.md` §8 数据管理** | P0 | 说明 atoms 在 `pim.db` 内，`./pim backup` 一并备份 |

### 不改 / 明确排除

- Obsidian vault — **无任何文档或同步说明**
- `docs/reviews/archive/*` — 历史归档不追改

### Task DOC-1: P0 文档（与 P0-8 并行）

- [ ] `USER_GUIDE.md` — § 新闻原子库（浏览、筛选、编辑、verified）
- [ ] `PIMCTL_REFERENCE.md` — atoms list/get/stats/verify/atomize
- [ ] `MODULE_BOUNDARIES.md` + `ARCHITECTURE.md` + `PROJECT_STRUCTURE.md` + `backend/README.md`
- [ ] `.env.example`

### Task DOC-2: P1 文档

- [ ] `PIMCTL_REFERENCE.md` — backfill / backfill-status
- [ ] `USER_GUIDE.md` — 自动提取说明、重新提取
- [ ] `TROUBLESHOOTING.md` — 提取故障树
- [ ] `AGENT_GUIDE.md` — Agent 查询原子示例脚本
- [ ] `VPS_DEPLOY.md` — 生产启用步骤

### Task DOC-3: P2 文档

- [ ] `PIMCTL_REFERENCE.md` — relations 子命令
- [ ] `USER_GUIDE.md` — 关系 Tab、矛盾确认流程
- [ ] `TROUBLESHOOTING.md` — 关系误判、reconcile 耗时

### Task DOC-4: 上线前总审（Week 4 末）

- [ ] 全库 grep `content_atom_bundles` / `AtomBundle` — 文档示例全部更新为归一化模型
- [ ] `pimctl --help` 与 `PIMCTL_REFERENCE.md` 命令列表一致
- [ ] `USER_GUIDE` 目录 TOC 更新
- [ ] 运维 runbook 一页纸（可写入 `USER_GUIDE` 或 `TROUBLESHOOTING`）：

```markdown
## 原子库运维 Runbook（Quick Reference）

启用：backend/.env 设 ATOMS_ENABLED=true → ./pim stop && ./pim up
验证：pimctl atoms stats --json
历史回填：pimctl atoms backfill --limit 200 --since 2026-01-01
跨文关系：ATOMS_RELATIONS_ENABLED=true → pimctl atoms relations reconcile
关闭：ATOMS_RELATIONS_ENABLED=false → ATOMS_ENABLED=false（保留 pim.db 数据）
回滚代码：flag 关闭即可；schema 回滚用 ./pim rollback <rev>（慎用，会丢 atoms 表）
备份：./pim backup（含 atoms）
```

---

## 文档更新（汇总 checkbox）

- [ ] DOC-1（P0 并行）
- [ ] DOC-2（P1）
- [ ] DOC-3（P2）
- [ ] DOC-4（上线总审）

---

## Spec Coverage Self-Check

| 设计文档要求 | 对应 Task |
|-------------|-----------|
| 四类 atom_type | P0-1（A/B/C）；P2（D 独立表） |
| 16 词表 | P0-1 vocab.py |
| 公共字段 | P0-1 types.py + P0-2 atoms 表 |
| atom_source 可信度 | P0-5 + P1-2 |
| 一 atom 一 type | P0-1 + P1-2 prompt |
| who 统一 | P0-1 WhoEntry |
| 人工 verified | P0-6 API + P0-8 前端 |
| 跨文 D 类 | P2 全系列 |
| pim.db 存储 | P0-2 migration |
| Obsidian 无关 | 全文无集成 |
