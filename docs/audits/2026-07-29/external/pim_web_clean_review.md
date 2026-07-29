# PIM Web Cleaning M0–M4 独立工程审计报告

- **审计对象**：`PIM_M0-M4_WebClean_Audit_b17e71e(1).zip`
- **用户声明基线**：`main @ b17e71ee0715cace333f6e2da3adfb1b29f9a5ae`
- **附件实测大小**：2,317,296 bytes
- **附件实测 SHA-256**：`fb6f09456496134e7217cb1b8352acc5e394b2615f75160cfc26ae07c1484fe2`
- **完整性检查**：`unzip -t` 通过；未发现 ZIP path traversal 条目
- **审计日期**：2026-07-29
- **审计边界**：仅附件完整源码快照、本地静态分析、fixture/mock 和可运行测试；未访问私有仓库、生产流量、真实登录态、真实用户数据或线上配置

> 附件不含 `.git`。因此，本报告可以确认压缩包哈希与用户给定值一致，也可以基于快照生成可应用补丁，但不能独立证明该快照确实由 Git 对象 `b17e71e...` 导出。为生成统一 diff，我仅在解压目录初始化了临时本地 Git 基线；未提交、推送或创建 PR。

---

## 1. 执行摘要

### 1.1 总体判定

**基线不能被认定为 “PIM_WEB_CLEANING_PRD.md 的 M0–M4 已完成”。**

仓库中已经存在一套较完整的 Web Clean 骨架，`CleanResult` 也不是孤立模块：website ingest 会在 Shadow/启用条件下调用 `ContentExtractor.extract_clean()`，执行 structured/template/readability/trafilatura/generic 候选，并把结果写入 `Content.metadata_.web_clean`。但是，基线同时存在会破坏生产安全与发布门禁的关键缺陷：

1. **Web Clean Markdown 在入库前被 `normalize_article_text()` / `strip_markdown()` 再次剥离**，标题、链接、图片、列表、代码围栏等结构实际无法持久化。
2. **只要全局 `PIM_WEB_CLEAN_ENABLED=true`，全部 website source 都可能覆盖生产正文**，没有 M3 所需的单 source 显式启用，也没有 M4 小流量灰度选择面。
3. **blocked/login/captcha/rejected 候选只要正文非空即可覆盖旧正文**，违反 fallback 与访问控制门禁。
4. **总发布 artifact 完全不检查 Web Clean 正式 Eval 和 7 天 Shadow**；即使 Web Clean 数据不存在，其他门禁满足时仍可能给出 GO。
5. 基线的 Shadow 报告语义不足以证明“连续 7 天、零生产影响、全部高风险样本人工复核”，存在把间断日期或被样本截断的风险项误当达标的可能。
6. 标准化、模板 DSL、Shadow DOM、structured metadata、probe、诊断包和 Reader/UI 都有实质缺口或安全边界不足。

本补丁修复了所有仅凭仓库即可确定和回归的缺陷，并保留旧 `ContentExtractor`/fallback、Shadow 默认、访问控制、付费导出和 fail-closed 原则。补丁**没有**制造 30/150 条假数据，也没有把 mock/fixture 结果描述为生产验收。

### 1.2 发布结论

| 决策 | 结论 |
|---|---|
| M0 | **部分完成**：工程合同和 runner 可用；30 条 bootstrap fixture、manifest、baseline artifact 缺失 |
| M1 | **工程实现基本完成，真实跨站验收未完成** |
| M2 | **部分完成**：source 模板 DSL、保存校验、probe 已接线；5–10 个内置模板及收益证据缺失 |
| M3 | **补丁后具备单 source 显式 write 门禁；尚未执行真实单源灰度** |
| M4 | **补丁后门禁工具 fail-closed；正式 ≥150 数据与真实连续 7 天 Shadow 缺失** |
| M5 默认启用 | **NO_GO** |

### 1.3 补丁后的生产行为

- `PIM_WEB_CLEAN_ENABLED` 仅作为**全局写入 master gate**。
- source 必须显式设置 `metadata_.web_clean_mode="write"` 才允许 Web Clean 候选替换正文。
- 未设置 mode 时默认 `shadow`；非法 mode 直接视为 `off`。
- `quality_status` 不是 `full/partial/good`、selected candidate 有 `rejected_reason`、trace 不一致或正文为空时，均不得替换旧正文。
- Shadow 仍只写有界诊断和 old/new hash/长度，不写原始 HTML、Authorization、Cookie、API Key 或默认敏感正文。
- 关闭全局 gate 后立即回到旧路径；没有新增数据库 schema/migration。

---

## 2. 审计方法与可信度边界

### 2.1 方法

1. 完整阅读 `PIM_WEB_CLEANING_PRD.md` 的 FR-1–FR-10、配置、API/CLI、M0–M5、指标、安全、测试和发布章节。
2. 追踪 `website collector → RawContent → ingest/build_content → Content.full_content/metadata → Reader/export/support bundle/frontend` 的真实调用链。
3. 不以文件存在或测试命名作为“已接线”证据；检查调用方、条件开关、持久化字段和 fallback。
4. 对确定缺陷先增加针对性测试，再实施最小修复；复测补丁后的路径。
5. 查找 PRD 要求的数据集、manifest、hash、baseline、内置模板、Shadow artifact 和 release artifact 接线。
6. 对 SSRF、登录态、Cookie、凭据、正文、正则/selector、HTML 大小、timeout、Shadow 隔离和付费边界做专项检查。

### 2.2 环境限制

- Python 3.13.5；Node 22.16.0；npm 10.9.2；uv 0.10.0。
- 容器已有 FastAPI、SQLAlchemy、BeautifulSoup、lxml、regex、pytest、pytest-asyncio、markdownify、Pydantic、Alembic。
- 缺少 `aiosqlite`、`readability-lxml`、`trafilatura`、`frontmatter`、APScheduler、feedparser、twikit、ruff、vulture 等完整项目依赖。
- 内部离线 Python 索引缺 `hatchling`/`ruff`；npm 内部仓库缺 `yocto-queue@0.1.0`，无法完成依赖恢复。
- 为进行**纯导入和定向单元测试**，使用了 `/tmp` 下最小 import stubs；这些 stub 不参与真实抓取、数据库异步 I/O 或生产质量验证。
- 无可用 Playwright 浏览器安装，因此不声称 E2E 通过。

---

## 3. FR-1–FR-10 Traceability Matrix

| FR | 基线状态与接线证据 | 独立审计结论 | 补丁后状态 | 外部/长稳阻塞 |
|---|---|---|---|---|
| **FR-1 HTML standardizer** | `WebDocumentExtractor.extract_sync()` 调用 `standardize_html()`，基线确实位于候选前；`html_standardizer.py` 有噪音删除和 URL 处理 | **部分实现且有 bug**：忽略 `<base>`；`data:` 可穿透；无 lazy media/noscript fallback；隐藏节点不足；selector 复杂度未统一限制；dangerous embed 未清理 | `html_standardizer.py:52-72,75-85,96-109,112-144,147-286`：base、attr-specific scheme、lazy/noscript、hidden、object/embed/applet、输入/输出 hash、输入/输出 cap、selector guard；测试覆盖 | 缺正式跨站 fixture、真实乱码/charset 与大页样本验证 |
| **FR-2 Shadow DOM** | `website.py` 只在 Playwright hydrate 后调用 materializer；基线 `website_shadow_dom.py` 仅复制 `host.shadowRoot.innerHTML` | **接线存在但实现不足**：嵌套 shadow root 不可递归复制；slot assigned nodes 丢失；无节点/深度/字符上限；timeout 结果未可靠进入 CleanTrace | `website_shadow_dom.py:1-126`：递归 clone、slot、root/node/depth/char/deadline 限制、HTML stamp；standardizer 消费 stamp；`CleanTrace` 透出 count/timeout | 未执行真实浏览器 E2E；closed shadow root 按浏览器边界不可访问 |
| **FR-3 structured** | `structured.py` 包装 `structured_article.py`，可遍历 JSON-LD 数组/@graph、多对象并取 article body | **部分实现且有 metadata bug**：`payload.setdefault("title", None)` 会阻止后续有效 title；`mainEntityOfPage`/language/image/canonical 不完整；结构化 body 被拒绝时 trace 不完整；递归遍历无界 | `structured.py:24-36,68-163` 与 `utils/structured_article.py`：多节点有界迭代、安全 http canonical/image、author/publisher/date/language、rejected trace | 缺正式 schema-rich 多站 gold；Next/bootstrap 的真实站点覆盖仍需外部样本 |
| **FR-4 templates** | source metadata 的 `web_clean_template` 能被读取；template candidate 优先于 generic；Source schema 基线已有保存校验 | **部分实现**：无 built-in host templates；未知顶层字段被忽略；trigger 使用 stdlib `re.search` 无 timeout；selector 复杂度弱；变量可命中过多节点；模板 `published` 渲染后未被 extractor 使用 | `templates.py:70-142,145-205`、`safety.py`、`extractors.py`：未知字段/类型/数量 fail-closed、regex timeout、selector guard、变量输出上限、published 解析；probe 返回 body-free preview | **5–10 个内置模板及“优于 generic”的评测证据缺失** |
| **FR-5 Filters DSL** | DSL 和 filter 名称基本齐全，regex substitution 已有 timeout/output cap | **部分实现且 fail-open**：参数个数未校验；`trim('x')`、缺参/多参可被接受；`remove_attr` 空参数可能扩大删除；replace flags 保存时未完整拒绝；`regex` 仅是传递依赖 | `filters.py:21-40,117-140,183-246`：严格 arity、replace pattern/flags、strip_attr 类型、selector guard、输出 cap；`regex` 加为直接依赖 | 正式模板兼容性仍需数据验证 |
| **FR-6 candidate scoring** | quality/scoring 模块被 extractor 调用；blocked/listing/schema 信号存在；template 低质量时可继续 generic | **候选生成已接线，但生产选择不安全**：基线 ingest 只检查 `article_text` 非空；blocked/rejected candidate 可写生产；部分失败 extractor 没有 rejected trace | `contracts.py:89-100` 增加 explainable `production_eligible()`；`build_content.py:70-104` 只允许显式 write 且 eligible；extractor 把 structured/template errors 有界写 trace | 阈值准确率必须由正式标注集和生产 Shadow 验证 |
| **FR-7 Markdown** | `web_clean.markdown` 存在；候选产生 Markdown；Exporter 仍有另一套 markdownify 配置 | **P0 接线 bug**：基线 `build_content.py:98-111` 把 Markdown 放入 `main_text`，随后 `normalize_article_text()` 调用 `strip_markdown()`；最终 `full_content` 是纯文本 | `build_content.py` 分离 canonical Markdown 与 quality plain text；`platform/export/html_markdown.py`/legacy extractor 复用统一 converter；代码语言、表格、blockquote、绝对链接 fixture 测试 | 无前端浏览器渲染 E2E；复杂脚注跨站保持需正式 fixture |
| **FR-8 入库/metadata** | `build_content.py` 基线会 stamp `Content.metadata_.web_clean` 和 source `web_clean_profile` | **已接线但门禁错误**：全局 enable 直接影响所有 website；metadata profile 缺 blocked/rejected/shadow diff；非法/未知 per-source mode 不存在 | `build_content.py:70-104,134-190`：`off/shadow/write`、blocked/recent failure、有界 diff；`CleanResult.to_metadata()` 保持兼容 | 真实 DB 长稳与 metadata 体积需生产前验证；补丁无 migration |
| **FR-9 UI/API/diagnostics** | 基线前端仅 source health 的有限 extraction method/score；Reader content detail 无诊断；probe 不做 clean preview；support bundle 不含 Web Clean trace | **部分实现** | `sources/probe.py:60-124,179-210`、`ProbeService.fetch_html():240-255` 复用 SSRF/cookie policy；`contents_reader.py:85-188` 严格 allowlist；`support_bundle.py:84-207,396-414` 脱敏；前端 health/Reader 面板接线 | npm lint/test/build 和浏览器 E2E 未执行；真实 UI 操作验收待外部环境 |
| **FR-10 Eval/Shadow gate** | 基线 eval 只算 sample/include/exclude/title/status/runtime；无 manifest/hash/tier；空标签可得到 1.0；总 release script 不认识 Web Clean | **未达到发布门禁** | `eval.py:92-213,216-369`：fixture hash、manifest、tier、label coverage、metadata/markdown/blocked/runtime；`run_web_clean_shadow.py:150-254`：连续日、provenance、隔离、全部高风险；release script `42-123` 强制 Web Clean | **正式 ≥150 数据、真实 production provenance、连续 7 天 Shadow、全部高风险人工复核均缺失** |

### API / CLI 核对

- `POST /api/sources/{id}/probe`：补丁后返回模板校验和不含正文的 clean preview；复用现有 SSRF 与 host-scoped cookies。
- content detail：补丁后 Reader payload 返回有界 `web_clean` 摘要，前端 ReaderPage 展示诊断。
- source health：source metadata 的 `web_clean_profile` 被现有 Source API 带出，FetchHealthDrawer 展示。
- `pimctl web-clean inspect/eval/shadow-report`：**仓库仍未实现**。PRD 10.2 使用“建议新增”，因此列为 P2 功能缺口，不作为伪造的 M0–M4 完成证据。仓库级脚本 `run_web_clean_eval.py` 和 `run_web_clean_shadow.py` 可供受控本地/CI 使用。

---

## 4. Milestone 逐项验收

| Milestone | PRD 要求 | 仓库事实 | 状态 |
|---|---|---|---|
| **M0** | 冻结合同；30 个 bootstrap fixtures；baseline；eval runner；生产不变 | `CleanInput/Candidate/Result/Trace` 与 runner 存在；仓库只有一个非 Web Clean `backend/tests/fixtures/eval_set.jsonl`，没有 Web Clean HTML 集、manifest、hash 清单或 baseline artifact | **部分实现；外部数据阻塞** |
| **M1** | standardizer、structured、Markdown、candidate scoring、基础 trace | 模块和 ingest 接线存在；基线有多项正确性/安全 bug，补丁已修并加回归 | **工程实现；真实跨站验收未完成** |
| **M2** | 模板 DSL、5–10 内置模板、probe、模板收益证据 | source template DSL 有基础；补丁补安全校验和 probe；仓库无任何 built-in host template | **部分实现** |
| **M3** | 单 source 手动启用；Shadow 默认；旧 fallback 可回滚 | 基线全局 enable 覆盖所有 website；补丁改成 source `web_clean_mode=write` 显式写入、默认 shadow、非法值 off | **补丁后工程门禁完成；真实单源灰度未做** |
| **M4** | 5%–10% 灰度、真实连续 7–14 天、formal gate、人工复核、release artifact | 基线没有 Web Clean 总门禁和可信 Shadow artifact；补丁补齐 fail-closed 工具链；仓库无真实报告 | **工程工具完成；真实验收外部阻塞** |
| **M5** | formal gate 达标后默认启用 | 所有正式数据与长稳条件尚未满足 | **NO_GO** |

---

## 5. Findings

## 5.1 P0 — 必须在任何生产写入前修复

### P0-01：Web Clean Markdown 实际入库时被剥离

**基线证据**

- `backend/app/domains/ingest/build_content.py` 基线 98–100：把 `article_markdown` 赋给 `main_text`。
- 同文件基线 111：立即调用 `normalize_article_text(main_text)`。
- `backend/app/utils/text.py` 的 `normalize_article_text()` 内调用 `strip_markdown()`。
- 同文件基线 164：`full_content=main_text_clean`。

**影响**

FR-7 声称的 heading、链接、图片、列表、表格、代码语言和 blockquote 不会真正进入持久化正文。单独测试 converter 无法发现此生产链路缺陷。

**修复**

- 生产正文保留 `article_markdown`；另生成 plain text 仅用于 summary、quality/filter 和去重信号。
- 新增 `test_web_clean_enabled_persists_markdown_while_quality_uses_plain_text`，明确断言链接和 ```python 围栏保留。

### P0-02：blocked/rejected 候选可覆盖旧正文

**基线证据**

- `build_content.py` 基线 98：条件仅为全局 enabled、`clean_result` 存在、`article_text` 非空。
- 没有检查 `quality_status`、selected candidate `rejected_reason` 或 trace 一致性。

**影响**

login wall、captcha、bot wall 或 rejected listing 可能替代已授权/旧 fallback 得到的正文；既是质量回归，也是访问控制语义错误。

**修复**

- `CleanResult.production_eligible()` 只允许 full/partial/good 且 selected trace 无 rejection；缺失/不一致 trace 直接不合格。
- ingest 仅在 `web_clean_write && production_eligible()` 时替换正文。
- 回归测试验证 login_required/rejected candidate 保留 legacy body。

### P0-03：全局开关等价于全站生产替换，不满足 M3/M4

**基线证据**

- `build_content.py` 基线 68–71：所有 website 只要全局 enabled 或 shadow 即执行。
- 基线 98–100：全局 enabled 即写生产，没有 source allowlist/mode。

**影响**

无法“只开一个 source”，也无法做 5%–10% 受控灰度；一个环境变量切换会把全部 website source 同时暴露于新路径。

**修复**

- source metadata 新增 `web_clean_mode=off|shadow|write`；默认 shadow；非法值 off。
- 全局 `PIM_WEB_CLEAN_ENABLED` 只是 write master gate；`PIM_WEB_CLEAN_SHADOW` 是 Shadow master gate。
- 回归测试验证全局 enabled 但 source 未 opt-in 时仍不写正文。

### P0-04：总 release gate 不检查 Web Clean

**基线证据**

- 基线 `backend/scripts/generate_release_eval_artifact.py:42-177` 仅检查 Core/Event、旧 quality Shadow、performance、approver。
- 无 Web Clean Eval、manifest/hash、Shadow、blocked F1、metadata、Markdown 或 runtime 条件。

**影响**

即使 Web Clean 完全无正式数据，发布 artifact 仍可能 GO，违反“缺正式数据 fail-closed”。

**修复**

- 总 artifact 必须接收 formal Web Clean report 与 7-day Shadow report。
- 强制 report v2、gate=GO、formal tier、manifest/hash、≥150 样本、所有关键标签、runtime、指标阈值。
- Shadow 强制 schema version、production provenance、连续天数、零隔离违规、全部高风险复核、`release_eligible=true`。
- CLI `--enforce` 在缺数据时实测退出 1，决策为 NO_GO。

### P0-05：Shadow “7 天/已复核”可被间断日期或样本截断误导

**基线/初版问题**

- 只看 observed day 数不能证明连续 7 天。
- 只比较展示 sample 的 reviewed_count，会漏掉展示上限之外的高风险样本。
- `production_shadow` 字符串本身不足以证明数据来自生产导出。

**修复**

- 计算 longest consecutive days。
- 分离 `total_count` 与 `sample_count`；release 需要 reviewed_count == total_count。
- production report 必须带独立 export attestation，且 `observations_sha256` 匹配输入文件。
- 不在内存长期保留未采样的敏感高风险行；只保留有界脱敏样本和计数。

## 5.2 P1 — 影响正确性、安全或可运维性

### P1-01：standardizer 的 URL/DOM 处理不完整

修复内容：

- 正确应用安全的 `<base href>`；trace 只记录布尔 `document_base_applied`，不保存可能含 token 的 base URL。
- `src/poster/srcset` 只允许 http/https；`href` 仅额外允许 mailto/tel/fragment；拒绝 data/javascript。
- lazy `data-src/data-srcset` 提升；noscript fallback materialize 后删除 noscript 容器。
- 删除 hidden/aria-hidden/display:none/visibility:hidden。
- 删除 object/embed/applet；保留表格、代码、链接、图片结构。
- 输入 byte cap、输出 cap、破损 HTML reparse、hash trace。

### P1-02：模板 trigger/selector/filter 可造成 fail-open 或 DoS

修复内容：

- 使用 `regex` 模块的执行 timeout；共享 regex 长度限制。
- selector 长度、token、combinator 与语法校验。
- 未知顶层字段、错误列表类型、超量 triggers/remove/filter/notes、未知 preset/variable/filter 均拒绝。
- filter 严格参数个数与 replace flags。
- selector 最多匹配 128 项，变量总输出最多 1,000,000 字符，超限报模板错误而不是静默截断。
- `regex` 从传递依赖改成直接依赖，锁文件仅增加 root dependency edge，版本沿用现有锁定 `2026.4.4`。

### P1-03：Shadow DOM materialization 不递归且无界

修复内容：

- 递归 clone nested open shadow roots；slot 使用 assignedNodes(flatten=true) 保留可见内容。
- 限制 roots/nodes/depth/chars 和 deadline；超时降级，不中断 collector。
- 在 DOM 上 stamp count/timeout，standardizer 读取后删除内部属性并写 CleanTrace。

### P1-04：structured 多对象 metadata 丢失与递归风险

修复内容：

- 取消会把 title 固定为 None 的 `setdefault` 行为。
- 支持 `mainEntityOfPage`、url、inLanguage、安全 image/canonical。
- JSON node 遍历改为最大 10,000 节点、深度 64 的迭代实现；过深内容不会触发 Python 递归崩溃。
- body 过短、过扁平、页面占比过低的拒绝原因写 trace。

### P1-05：Eval 可被空标签或无 provenance 的 fixture “做高分”

修复内容：

- release tier 不允许 inline HTML 代替 hashed fixture。
- manifest 必须声明 tier、sample count、dataset SHA、fixture SHA；formal 还需 baseline runtime p95。
- 关键标签计数为 0 时门禁失败；聚合指标不再把空标签默认成 1.0。
- 新增 canonical/date/markdown/min chars/blocked precision-recall-F1/metadata accuracy/runtime。
- formal 覆盖要求中英文、paywall/non-paywall、article/spa/schema-rich/table/code 等类型。

### P1-06：Probe/Reader/support bundle 的 Web Clean 诊断不闭环

修复内容：

- manual source probe 在抓取前验证模板；无效模板不发请求。
- 有效模板使用 `ProbeService.fetch_html()`，复用 SSRF 与 host-scoped cookies；preview 只返回 method/status/score/chars/blocked 等标量，不返回正文/HTML。
- Reader 只输出严格 allowlist；canonical 去 userinfo/query/fragment；NaN/Infinity、嵌套 shadow payload、hash 超长值被拒绝/截断。
- support bundle 增加 pseudonymous content/source refs、有界 candidate/standardizer trace；排除 title/url/body/raw HTML/cookies/Authorization/API Key；非有限数字不输出。

## 5.3 P2 — 不应伪装为完成的缺口

1. **没有 30 条 Web Clean bootstrap fixtures、manifest、baseline artifact。**
2. **没有 formal Web Clean Eval 1.0 的 ≥150 条人工标注数据。**
3. **没有 5–10 个内置 host templates，也没有模板相对 generic 的收益报告。**
4. **没有真实 production export provenance 和连续 7 天 Shadow artifact。**
5. **没有 M4 5%–10% 小流量灰度记录和全部高风险人工复核。**
6. **没有 `pimctl web-clean ...` 命令。**
7. **当前环境无法执行前端 lint/test/build 和浏览器 E2E。**
8. `readability-lxml`/`trafilatura` 未安装于审计容器，因此本次只验证其 import-fallback 及统一候选编排，不能声称两种真实 extractor 的生产效果通过。

---

## 6. 补丁内容

### 6.1 生产接线与 fallback

- 修复 Markdown 持久化。
- 增加 source `off/shadow/write`。
- 增加 candidate production eligibility。
- 保留旧 structured/legacy extractor fallback；新路径异常时继续旧路径。
- 没有改变 paid fulltext export 的保护逻辑。

### 6.2 安全与资源边界

- HTML 输入/输出 cap 未放宽。
- Web Clean timeout 未放宽。
- selector/regex/filter/变量输出改为更严格的 fail-closed。
- Shadow DOM 增加而非取消节点/深度/字符/时间限制。
- Probe 复用 SSRF 校验，不绕过登录/访问控制。
- diagnostics 不保存 raw HTML/正文/credential/header/cookie/token。

### 6.3 Eval/Shadow/release

- 新增 provenance-aware Web Clean eval v2。
- 新增只消费外部导出 JSONL 的 `run_web_clean_shadow.py`；脚本自身不抓 URL、不读取凭据、不改 Content。
- release artifact 强制 Web Clean formal report + production Shadow。
- 缺数据、缺标签、缺 manifest/hash、非连续天、未复核、隔离违规均 NO_GO。

### 6.4 API/UI/测试/文档

- source probe template validation + body-free preview。
- source health 与 Reader content detail Web Clean diagnosis。
- support bundle 有界脱敏诊断。
- `PIM_WEB_CLEANING_PRD.md` 增加“实施状态与证据（独立审计）”，明确工程完成与真实验收差异。

### 6.5 依赖与迁移

- 新增直接 Python 依赖：`regex>=2024.11.6`。该包此前已被 `dateparser` 传递锁定；未引入新版本或 sidecar。
- 无 Node/Defuddle sidecar。
- 无数据库模型/schema 变化，无新增 Alembic migration。
- 前端 package/lock 未修改。

---

## 7. 测试与命令执行记录

### 7.1 已通过

| 命令/范围 | 结果 | 说明 |
|---|---:|---|
| Web Clean standardizer/filters/templates/markdown/extractors/eval/shadow DOM | **35 passed** | 使用当前源码 + import-only stubs；readability/trafilatura 实包缺失 |
| support bundle、probe、Reader summary、ingest write/shadow/fallback、release/shadow 定向测试 | **16 passed** | 4 个现有 `datetime.utcnow()` deprecation warnings |
| 独立 `test_web_clean_release_gate.py` | **4 passed** | provenance、redaction、formal metric gate |
| `test_website_parser.py --no-cov` | **15 passed** | fixture parser |
| `test_fetch_failures.py --no-cov` | **32 passed** | failure taxonomy |
| `test_postprocess_jobs.py --no-cov` | **4 passed** | sync SQLite lifecycle |
| `test_alembic_fresh_upgrade.py --no-cov` | **1 passed** | 临时 DATA_DIR；stub 仅满足 aiosqlite import，实际 migration 使用 sync SQLite |
| `python -m compileall -q backend/app backend/scripts backend/tests` | **通过** | 全量 Python 语法编译 |
| `python backend/scripts/check_domain_imports.py` | **通过** | 402 files，依赖方向 clean |
| `python backend/scripts/check_ble001_budget.py` | **通过** | 0 <= 188 |
| `git diff --check` | **通过** | 无 whitespace/error |
| Web Clean formal-tier CLI（1 条本地 fixture、无 manifest，`--enforce`） | **退出 1 / NO_GO** | 正确报告 manifest、label、sample、runtime baseline 等 blockers |
| release artifact CLI（缺全部正式输入，`--enforce`） | **退出 1 / NO_GO** | 正确报告 Core/Event/Web Clean/Shadow/performance/approver 缺失 |

上述最终可计数的通过测试共 **107 项**。这些测试证明代码路径和 fail-closed 行为，不代表生产网站质量验收。

### 7.2 未完成或不能声明通过

| 命令 | 实际结果 | 结论 |
|---|---|---|
| `ruff check app` | `ruff: command not found`，exit 127 | **未运行** |
| backend `pytest -q --no-cov` | conftest 导入时 `ModuleNotFoundError: aiosqlite`，exit 4 | **全量未运行** |
| `test_website_collector.py` | 显示约 121 个进度点后在当前 stub 环境 teardown/进程退出阶段超时，无 pytest summary | **不能声称通过** |
| 探索性相关组合 suite | 曾到 166 passed 后遇到 feedparser stub 行为差异和缺 twikit；随后 teardown 超时 | **不计入最终通过数** |
| `uv sync --frozen --extra dev` | 内部离线索引无 `hatchling` | **环境阻塞** |
| `uv lock --check` | 内部索引无 `ruff==0.6.9`，解析失败 | **不能据此判定锁文件错误**；人工 diff 只增加现有 regex root edge |
| `npm ci --ignore-scripts --no-audit --no-fund` | 内部仓库 404：`yocto-queue@0.1.0` | **环境阻塞** |
| `npm run lint` | `eslint: not found`，exit 127 | **未运行** |
| `npm run test -- --run` | `vitest: not found`，exit 127 | **未运行** |
| `npm run build` | 缺 react/types/vite 等 node_modules，tsc 大量 module-not-found，exit 2 | **未通过，根因是依赖未安装；不等于补丁 TS 正确性已验证** |
| 浏览器 E2E | 无浏览器依赖 | **未运行** |
| `check_dead_code.py` | 缺 vulture | **未运行** |
| `check_file_lines.py` | 报告两个补丁前已存在的超限文件：`pim` 1742>1687、`CredentialsTab.tsx` 985>975 | 与本补丁无新增关系，但命令未绿 |

---

## 8. 外部阻塞与后续验收计划

以下事项无法仅靠本仓库诚实完成，必须继续保持 release gate fail-closed：

1. **M0 bootstrap 数据**：从合法可保存的生产/测试来源选 30 个 HTML fixtures，覆盖中英文、schema-rich、SPA、listing、login wall、captcha、表格、代码、图片、付费提示；建立 manifest 和每个 fixture SHA-256。
2. **M0 baseline**：在同一数据集上保存旧 pipeline baseline artifact，不得事后改标签迎合新结果。
3. **M2 内置模板**：选择 5–10 个合法站点，模板必须有 owner/version/trigger/fixture/gold；只有相对 generic 有稳定收益才合入。
4. **M4 formal set**：≥150 条人工标注；至少两位标注者或有 adjudication 记录；manifest 含 dataset/fixture hashes 和 baseline runtime p95。
5. **真实 Shadow**：由独立生产导出流程生成带 attestation 的标量 JSONL；连续至少 7 天，推荐 14 天；不得导出正文、URL query、Cookie、Authorization 或凭据。
6. **人工复核**：所有高风险样本全部有 verdict，不能只复核 UI 展示的前 50 条。
7. **受控灰度**：先单 source，再 5%–10%；记录 source allowlist、开始/结束日期、rollback 演练、旧/新指标和异常处置。
8. **付费/登录态**：仅使用用户已授权的正常抓取链路；不得 archive mirror、绕过 paywall 或扩展导出权限。
9. **完整 CI**：在可安装 lockfile 的标准环境执行 ruff、backend 全量、frontend lint/test/build 和真实 Playwright E2E。

---

## 9. 建议写回 PRD 的状态表

补丁已把以下表写入 `PIM_WEB_CLEANING_PRD.md` 第 21 节；建议保留为唯一进度口径：

| 项目 | 建议状态 |
|---|---|
| FR-1 | 工程已实现并接线；正式跨站 fixture 验收缺失 |
| FR-2 | 工程已实现并接线；真实浏览器 E2E 缺失 |
| FR-3 | 工程已实现并接线；schema-rich 正式 gold 缺失 |
| FR-4 | 部分完成；source template/probe 已有，built-in templates 缺失 |
| FR-5 | 工程已实现；正式模板兼容性待验收 |
| FR-6 | 工程已实现；阈值需 formal data/Shadow 验证 |
| FR-7 | 工程已实现并修复生产 Markdown 持久化；浏览器渲染待验收 |
| FR-8 | 工程已接线；source write gate 已具备；真实 DB 长稳待验收 |
| FR-9 | 工程基本闭环；前端完整 CI/E2E 缺失 |
| FR-10 | 门禁工具已实现；正式数据和真实 7 天 Shadow 缺失，NO_GO |
| M0 | 部分实现 / 数据阻塞 |
| M1 | 工程完成 / 真实验收未完成 |
| M2 | 部分实现 |
| M3 | 工程接线完成 / 灰度未执行 |
| M4 | 门禁工程完成 / 真实验收阻塞 |
| M5 | **不具备默认启用条件** |

---

## 10. 最终意见

1. **可以合并并评审本补丁作为 M0–M4 的工程修复基础**，因为它修复了生产正文破坏、blocked candidate 写入、全局无差别启用和 release gate 漏检等确定缺陷。
2. **不能把补丁合并等同于 M0–M4 验收完成**。M0 数据、M2 内置模板、M4 正式数据/真实连续 Shadow 都是明确未完成项。
3. **M5 默认启用必须继续 NO_GO**。在正式 Web Clean Eval v2 和真实 production Shadow 均提供且总 release artifact 给出 GO 前，保持全局写开关关闭，source 默认 Shadow。
4. 不建议在当前补丁默认路径引入 Node/Defuddle sidecar；仓库没有可信对照评测证明收益大于复杂度与运维风险。

