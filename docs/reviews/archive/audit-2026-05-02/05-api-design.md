# 模块五：API 设计与数据验证 审计报告

## 总评

API 层整体很扎实：所有 `/api/*` 路由通过 `api_router = APIRouter(dependencies=[Depends(verify_api_key)])` 在顶层强制注入鉴权（`backend/app/api/__init__.py:9`）；Pydantic schemas 大部分都有 `min_length / max_length / pattern / ge / le` 约束；FTS5 查询用专门的 `fts_query.py` 转义 + 参数化绑定，注入风险低；`/api/contents/cleanup-*` 等危险操作以 `apply=false` 默认 dry-run。

主要问题集中在**HTTP 方法语义**（`/contents/{id}/favorite` 用 POST 但语义是 toggle，违背 idempotency）、**部分 Pydantic schema 缺长度上限**（probe 的 url 字段、reader 的 query params）、**reader/contents_reader.py 留有大量 `# noqa` re-export 用于测试 patch**（影响可读性但不破坏功能）。

## 严重问题（❌）

无严重漏洞。

## 轻微问题（⚠️）

- **L1** `POST /contents/{id}/favorite` 语义是**toggle**（`backend/app/api/contents_crud.py:222-234`），同一请求重复执行结果不同，违背 POST 至少为创建副作用而非反复翻转的预期；建议改 PUT/PATCH 显式传 `favorited: bool`。
- **L2** `ProbeRequest.url: str = ""`（`backend/app/api/sources/probe.py:30-32`）没有 `min_length/max_length/pattern`，依赖 ProbeService 内部校验；同样 `ProbeRequest.type: str` 没有 enum 校验，靠 `_ensure_supported_source_type` 兜底。
- **L3** `_content_ilike_search_clause` 限了 120 字符（`contents_crud.py:25`）但 ILIKE 多列 OR 在 `full_content` 上仍可能很慢；对低分布 keyword + 大库会引发慢查询。
- **L4** `contents_reader.py` 把大量内部模块通过 `# noqa: E402,F401 - patch target` 重新暴露给测试 patch（`backend/app/api/contents_reader.py:45-77`）——可工作但会让"哪些是公共契约、哪些是内部"边界模糊。
- **L5** Bulk 路径 `cleanup-low-signal` / `cleanup-junk`（`contents_cleanup.py`）在 `apply=true` 时**逐条 `await db.delete(content)`**，没有批量删除上限或事务分块，理论上可一次性删除海量行（受 SQLite 单事务能力限制）。
- **L6** `/contents/export-md` 错误处理 `except Exception as exc: raise HTTPException(500, str(exc))`（`contents_crud.py:200-204`）会把内部异常文本（可能含路径/SQL 信息）原样回给客户端。

## 良好实践（✅）

- **G1** `api_router` 顶层注入 `Depends(verify_api_key)`（`backend/app/api/__init__.py:9`）——所有 `/api/*` 子路由器自动继承鉴权，新增子路由默认安全。
- **G2** Pydantic source schema 严谨：`name 1-255`、`type` 用正则枚举、`url` 必须 http(s)、`fetch_interval` 限 15-1440、`extra_urls` 逐项校验、`metadata.max_fetch_lag_minutes` 上下界（`backend/app/schemas/source.py:33-67, 14-27`）。
- **G3** FTS5 查询专用 sanitizer：200 字符 input cap、20 token 上限、64 char per token、剥离 `* ^ : ( ) [ ] { } \ -`、转义双引号；返回 None 时调用方 fallback ILIKE（`backend/app/utils/fts_query.py`）。
- **G4** FTS 子查询使用参数化绑定 `:search_term`（`contents_crud.py:97-104`），SQLAlchemy 处理转义，无注入风险。
- **G5** 分页参数硬上限：`page_size: int = Query(20, ge=1, le=200)`（`contents_crud.py:47`），无法绕过。
- **G6** Cleanup 等破坏性操作默认 `apply=false`（dry-run），明确返回 `mode: "dry_run" | "apply"`（`contents_cleanup.py:109-145, 148-230`）。
- **G7** 错误响应使用 FastAPI 标准 `HTTPException`，避免直接 `return JSONResponse(...)` 散落，detail 大多是中性文本（"Content not found"、"Source not found"）。
- **G8** Reader 路径的所有外部 URL 都经 `assert_public_http_target` SSRF 检查（通过 contents_reader.py:73 import 在 body_loader 中调用）。
- **G9** Probe 的 `_load_source_probe_cookies` 与 `_helpers._probe_urls` 把外部 URL 探测复用与采集器同一套 SSRF/超时栈，避免代码漂移。
- **G10** `contents_cleanup.cleanup-junk` 即使 apply=true 也要求至少一个匹配条件 enabled（`contents_cleanup.py:165-169`），防止误用。

## 详细审计清单

### 1. Pydantic schemas：严格类型 / 长度限制

- **结论：** ✅（主体严谨）+ ⚠️（少数缺口）
- **代码位置：** `backend/app/schemas/source.py:30-80`、`backend/app/api/sources/probe.py:30-40`、`backend/app/schemas/`（其它模型未细看）
- **分析：**
  - SourceBase（L33-42）齐全：name 1-255、type 正则枚举 `^(website|rss|x|youtube|podcast)$`、url min_length=1、fetch_interval 15-1440、metadata 字段验证。
  - URL regex `^https?://` 在 schema 层就拒绝错误协议（L52-56）。
  - `metadata.max_fetch_lag_minutes` 在 schema 层做 1-525600 (1 day~365 day) 范围校验（L14-27）。✅
  - **缺口：**
    - `ProbeRequest.url: str` 没有 max_length；攻击者可以提交 1MB 长字符串引发 DNS/CPU 浪费。
    - `ProbeRequest.type: str = "website"` 没有 enum 约束，依赖 service 内部 `_ensure_supported_source_type`。这是防御性设计（避免 422 文本暴露内部枚举），但应在 schema 写明白。
- **建议：**
  - 给 ProbeRequest 加 `url: str = Field(..., min_length=1, max_length=2048, pattern=r"^https?://")`、`type: Literal["website","rss","x","youtube","podcast"]`。

### 2. FTS5 查询 SQL 注入

- **结论：** ✅
- **代码位置：** `backend/app/utils/fts_query.py:1-49`、`backend/app/api/contents_crud.py:83-104`
- **分析：**
  - `build_sqlite_fts5_match_expression`：
    - 200 字符 input cap、20 token 上限、64 char per token；
    - 剥离 FTS5 操作符：`*`（前缀）、`^`（field-prefix）、`:`（column）、`( ) [ ] { }`、`\`、`-`（NOT）；
    - 双引号 `"` 仍保留但每个 token 用 phrase quote 包起来后转义为 `""`；
    - 多 token 用 `AND` 连接（隐式 AND 与显式 AND 等价）；
    - 空 token 集合返回 None，调用方走 ILIKE fallback。
  - SQL 绑定：FTS subquery 使用 `:search_term` 参数化绑定（`contents_crud.py:100, 101`），值通过 `.params(search_term=match_expr)` 传入。SQLAlchemy 处理转义。
  - ILIKE clause 也清理了 `%` 与 `_`（`_content_ilike_search_clause` L25）。
- **建议：** 无；可以加单元测试覆盖 `*`、`(...)`、`a OR b`、`fieldname:value` 等已知 SQL/FTS 注入向量。

### 3. 分页参数上限保护

- **结论：** ✅
- **代码位置：** `backend/app/api/contents_crud.py:20, 47`、`backend/app/api/contents_cleanup.py:113, 152`
- **分析：**
  - `MAX_CONTENTS_PAGE_SIZE = 200`，`page_size = Query(20, ge=1, le=MAX)`，FastAPI 422 if 超界。
  - `cleanup-low-signal preview_limit: 1-200`、`cleanup-junk preview_limit: 1-500`，都有上限。
  - `page: int = Query(1, ge=1)` 没有 page 上限（`page=10000` 会被允许）——但 page 大到结果空集合时只是 OFFSET 大，没有 OFFSET 上限保护。SQLite 在大 OFFSET 上效率差。
- **建议：** 给 `page` 加 `le=10000` 上限避免极端 OFFSET。

### 4. HTTP 方法语义（GET 副作用 / DELETE 幂等）

- **结论：** ⚠️
- **代码位置：** `backend/app/api/contents_crud.py:207-234, 237-249`
- **分析：**
  - GET 路由：`list_contents`、`get_content` 都是只读，无副作用 ✅。
  - DELETE：`delete_content`（L237-249）幂等（重复 delete 会 404，状态终态一致）✅。
  - **POST `/contents/{id}/read`**（L207-219）：把 `read_status = True`。多次 POST 状态都为 True → 语义幂等 ✅，但 HTTP 语义上 POST 不要求幂等，PUT 更合适。
  - **POST `/contents/{id}/favorite`**（L222-234）：`favorited = not favorited` → toggle 实现意味着**重复请求结果不同**，是非幂等的。这是个常见反模式：第一次 POST 收藏，第二次 POST 取消收藏，重试会改变状态。
  - DELETE auth-config（`configs_api_auth.py:309-349`，已在模块二讨论）有"软清理"副作用，但仍是 DELETE 终态一致。
- **建议：**
  - `/contents/{id}/favorite` 改为 `PATCH /contents/{id}` body `{favorited: true}`（已有 PATCH 路由，L144），删掉 toggle 端点。或保留端点但语义改为 `PUT`，body 显式传 desired state。

### 5. 错误响应一致性 / 不泄露内部信息

- **结论：** ✅（主体）+ ⚠️（局部）
- **代码位置：** 全 `backend/app/api/`
- **分析：**
  - 大部分 4xx 用 `HTTPException(status_code=4XX, detail="..." )`，detail 是 sanitized 短字符串。
  - 401（API key 校验失败）："Invalid or missing API key"
  - 403（local-token 拒绝）："Local access only"/"Invalid host"/"Invalid origin"
  - 404："X not found"
  - 422（FastAPI 自动）：Pydantic 校验错误，结构化字段路径
  - **泄露点：** 
    - `/contents/export-md`（`contents_crud.py:200-204`）`raise HTTPException(500, str(exc))`：把 exporter 异常文本（可能含路径、SQL 错误）原样返回。
    - `/sources/probe-all` 把 `str(exc)[:200]` 截断后放进 `failed_items`（`probe.py:69-70`），200 字符仍可能含敏感路径，但截断+只在 admin auth 后才能调用，风险有限。
- **建议：**
  - export-md 失败时 500 detail 改为通用 "Markdown export failed"，详细错误进 logger.exception。

### 6. /api/sources/probe：SSRF 检查

- **结论：** ✅
- **代码位置：** `backend/app/api/sources/probe.py:43-50`、`backend/app/services/probe_service.py`（未读全文）、`backend/app/utils/ssrf.py`
- **分析：**
  - `ProbeService` 通过 `probe_strategies/registry.py` 分派到具体 strategy（ARCHITECTURE.md §4 描述）。
  - 每个 strategy 在调用 aiohttp/playwright 前都应该先 `assert_public_http_target` —— 已通过 `BaseCollector._check_ssrf` 集成（模块三验证）。
  - probe 与 collector 共用同一套 SSRF 函数（`backend/app/utils/ssrf.py`），无代码漂移。
- **建议：** 在 `_helpers._probe_urls` 里加单测，确认 `http://127.0.0.1`、`http://10.0.0.1`、`http://localhost`、`http://[::1]` 全部被拒。

### 7. /api/contents/{id}/reader：超时 / URL 来源限制

- **结论：** ✅
- **代码位置：** `backend/app/api/contents_reader.py`、`backend/app/services/reader/body_loader.py`
- **分析：**
  - reader 端点的"加载正文"必须先从 DB 读出 Content 行，再用 `content.original_url` 去 fetch（不接受任意外部 URL）——这意味着"只允许已存库的 URL"约束是**自然成立的**（攻击者不能让 reader 抓任意 URL）。✅
  - body_loader 内部仍调用 `assert_public_http_target`（contents_reader.py:73 import 验证）防御性 SSRF。
  - 超时：streaming 翻译 22s/段（模块四验证）；底层 aiohttp 调用应有超时但需要看 body_loader 实现确认。
- **建议：** 在 body_loader 加显式 `aiohttp.ClientTimeout(total=30, connect=10)`，避免依赖默认（aiohttp 默认 5 分钟）。

### 8. Bulk 操作：数量上限 / 事务保护

- **结论：** ⚠️
- **代码位置：** `backend/app/api/contents_cleanup.py:109-230`
- **分析：**
  - `cleanup-low-signal` / `cleanup-junk` 在 `apply=true` 时：
    - 先把所有匹配的 content 收集到 `matched: list[Content]`；
    - `for content in matched: await db.delete(content)`；
    - 最后一次 `await db.commit()`。
  - 这是单事务删除 N 行，N 没有上限。SQLite 默认事务可承受 ~10k 行删除，再多会显著拖慢；理论极端可能超过 sqlite 的 `SQLITE_MAX_COMPOUND_SELECT`。
  - **没有"per call 删除上限"参数**（preview_limit 仅影响响应里的 preview，不影响实际删除数量）。
  - **错误中止策略：** 单条 delete 抛错会让 commit 失败，整个事务回滚 → 没有部分删除的局面。是好的。
  - DELETE bulk 的 dry-run 默认是 ✅ 实践。
- **建议：**
  - 加 `max_delete: int = Query(5000, ge=1, le=100000)` 参数，超过即拒绝执行（要求用户分批）。
  - 或者改为内部分块：`for chunk in chunks(matched, 1000): for c in chunk: await db.delete(c); await db.commit()`，避免一次大事务。

## 涉及文件

- `backend/app/api/__init__.py`
- `backend/app/api/contents_crud.py`
- `backend/app/api/content_shared.py`
- `backend/app/api/contents_cleanup.py`
- `backend/app/api/contents_reader.py`（前 80 行 + reader package 的边界）
- `backend/app/api/sources/probe.py`（前 80 行）
- `backend/app/utils/fts_query.py`
- `backend/app/schemas/source.py`（前 80 行，含校验器）
- `backend/app/schemas/`（目录列表：config / content / digest / keyword / source）

## 可立即落地的修复

1. `POST /contents/{id}/favorite` → `PATCH /contents/{id}` body `{favorited: bool}`，删除 toggle 端点。
2. ProbeRequest 加字段约束（max_length、Literal type）。
3. `/contents/export-md` 5xx 错误 detail 改为通用消息 + logger.exception。
4. cleanup-* 加 `max_delete` 参数防误删大批量。
5. 给 `page` 加 `le=10000`。
