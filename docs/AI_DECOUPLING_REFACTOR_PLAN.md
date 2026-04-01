# PIM 模型解耦与简报重构规划

日期：2026-03-30

## 1. 目标

这次改造要解决的不是单点性能问题，而是系统职责边界不清的问题。

目标是把 PIM 明确定义为：

- 一个以抓取、过滤、去重、入库、检索、阅读为核心的内容系统
- 一个可以接入大模型能力的增强系统
- 一个在未配置任何大模型时依然完整可用的系统

不再把抓取链路和模型链路耦合在一起。

## 2. 已确认的产品决策

### 2.1 PIM 与模型的关系

- PIM 与大模型是解耦关系
- 模型能力是可选增强，不是主路径依赖
- 云端模型、Ollama、本地模型都应通过统一抽象接入

### 2.2 模型的职责

模型只负责两类能力：

- 翻译
- 小时报简报生成

其它核心能力不依赖模型。

### 2.3 翻译策略

- 翻译改为按需触发
- 只有用户点击“看译文”后，才对当前内容发起翻译
- 翻译结果必须缓存，避免重复消耗 token / 算力

### 2.4 简报策略

- 小时报作为整点定时任务执行
- 读取上一个 60 分钟内的新内容
- 先做规则筛选、排重、聚类、粗排序
- 再交给模型生成最终目标语言简报

### 2.5 无模型时的行为

- 无模型时保留抓取、阅读、检索等核心能力
- 明确不提供简报功能

### 2.6 简化排序策略

排序不做复杂评分体系，第一版只保留最小可行规则：

- 多个信源重复报道的事件优先
- 已在之前简报中覆盖过的事件不再重复
- 更完整、篇幅更长的内容优先
- 可保留一个轻量来源优先级加成，但不做复杂权重体系

### 2.7 信源上限

- 系统应增加信源数量上限
- 建议默认上限：`200`
- 上限必须后端强校验，前端做提示
- 该值应可配置，不写死在 UI 中

## 3. 当前代码现状

### 3.1 抓取后处理仍混入模型调用

当前 [content_processor.py](/Users/shuhuaiwang/personal-info-monitor/backend/app/processors/content_processor.py) 在 `process()` 中做了：

- 生成摘要
- 翻译标题
- 翻译摘要

这意味着批量抓取越大，模型处理越容易成为瓶颈。

### 3.2 翻译链路已经部分具备按需雏形，但还不彻底

当前 [contents.py](/Users/shuhuaiwang/personal-info-monitor/backend/app/api/contents.py) 的 reader 接口已经会：

- 在读取正文时按需翻译
- 并把全文译文缓存在 `metadata.reader_translated_full_content`

这说明“按需翻译”已经有基础，但入库链路里仍然存在标题/摘要翻译，职责没有完全分开。

### 3.3 简报任务已经独立，但模型耦合方式还不理想

当前 [hourly_digest_tasks.py](/Users/shuhuaiwang/personal-info-monitor/backend/app/tasks/hourly_digest_tasks.py) 已经是一个独立定时任务，并且会：

- 拉取上一小时内容
- 用 [ranking_service.py](/Users/shuhuaiwang/personal-info-monitor/backend/app/services/ranking_service.py) 做聚类和排序
- 直接调用 Ollama 生成最终简报

问题在于：

- 模型调用仍写死在任务文件里
- 当前 `Summarizer` / `Translator` / `hourly_digest_tasks` 各自维护 provider 逻辑
- “是否已有上一轮简报覆盖”还没有进入排序逻辑
- `HourlyDigest` 模型目前没有保存事件指纹，难以做去重延续

### 3.4 scheduler 当前是按总开关启用 AI

[scheduler.py](/Users/shuhuaiwang/personal-info-monitor/backend/app/scheduler.py) 现在使用 `ai_processing_enabled` 统一控制 AI 任务注册。

后续应改成更细粒度：

- `translation_enabled`
- `hourly_digest_enabled`
- 或根据 provider availability 动态判定

## 4. 目标架构

建议把系统拆成 4 层。

### 4.1 Content Core

负责：

- 抓取
- 过滤
- 去重
- 入库
- 检索
- 阅读原文

这层永远不依赖模型。

### 4.2 AI Provider Layer

新增统一 provider 抽象，例如：

- `translate(text, target_language, ...)`
- `generate_hourly_digest(prompt_or_payload, ...)`
- `is_available()`
- `provider_name()`

实现层包括：

- OpenAI provider
- Ollama provider
- future provider

这层不感知抓取流程，只提供能力。

### 4.3 AI Use Cases

这一层封装业务动作，而不是底层 provider：

- `TranslationService`
- `HourlyDigestService`

Use case 层负责：

- 参数组织
- prompt 结构
- fallback 规则
- 缓存策略
- 失败降级

### 4.4 Entry Layer

入口包括：

- 前端 reader 页面
- scheduler 定时任务
- CLI / agent 调用

入口层只调用 use case，不直接操作 provider。

## 5. 翻译改造方案

### 5.1 目标状态

抓取阶段不再调用翻译模型。

只有在用户阅读时，才对当前内容发起翻译。

### 5.2 具体改造

#### A. 移除入库阶段翻译

修改 [content_processor.py](/Users/shuhuaiwang/personal-info-monitor/backend/app/processors/content_processor.py)：

- 不再在 `process()` 中生成 `translated_title`
- 不再在 `process()` 中生成 `translated_summary`
- 不再把模型调用放在批量抓取路径里

第一版可以保留原字段，但停止继续写入，避免大范围数据库变更。

#### B. 正式定义按需翻译接口

当前 reader 接口已经会按需翻译全文，建议整理为正式能力：

- `GET /api/contents/{id}/reader` 继续支持按需翻译
- 增加明确的 `translate=true/false` 语义，避免未来歧义
- 或新增 `POST /api/contents/{id}/translate`

建议第一版先保持 reader 路径不拆，减少前端改动。

#### C. 缓存策略

第一版继续复用 `metadata.reader_translated_full_content` 即可。

后续如果需要更清晰的数据结构，再考虑新增字段或独立表：

- `translated_full_content`
- `translated_full_content_updated_at`
- `translation_provider`
- `translation_model`

#### D. 前端交互

阅读页改为：

- 默认只展示原文
- 用户点击“看译文”时再请求翻译
- 翻译中显示 loading
- 若模型不可用，明确提示“当前未配置翻译模型”

### 5.3 预期结果

- 抓取吞吐量与模型速度彻底解耦
- token 成本显著下降
- 本地 Ollama 也能被接受，因为翻译属于用户主动行为

## 6. 小时报重构方案

### 6.1 目标状态

小时报是一条独立的“整点批处理 pipeline”，不参与抓取主链路。

只有在模型可用且简报功能启用时，才生成简报。

### 6.2 Pipeline

建议将小时简报拆成 5 步。

#### Step 1. 读取候选内容

读取过去 60 分钟的新内容：

- 仅网站类内容
- 排除低质量内容
- 排除正文过薄内容
- 排除已归档无关项

#### Step 2. 规则预处理

在模型之前先做：

- 标题/正文近似去重
- 事件聚类
- 统计同事件信源数量
- 标记长文 / 短文
- 生成事件指纹

这里继续基于 [ranking_service.py](/Users/shuhuaiwang/personal-info-monitor/backend/app/services/ranking_service.py) 演进，而不是重写。

#### Step 3. 最小排序策略

按以下规则排序：

1. 多信源重复报道优先
2. 未在前序简报中出现过的事件优先
3. 正文更长、更完整的文章优先
4. 同分时再参考来源优先级与时效

不做复杂的综合评分体系。

#### Step 4. 模型生成

只把前 N 个候选事件簇交给模型。

模型负责：

- 用目标语言生成完整简报
- 按自然段组织，不写流水账
- 合并同一事件不同来源
- 在每段附上原始链接出处

#### Step 5. 落库与历史去重

保存：

- 简报正文
- 使用到的 source 名单
- 内容数量
- 事件指纹列表

“事件指纹列表”是为了下一小时去重。

### 6.3 为什么要保存事件指纹

因为你已经明确要求：

- 如果之前的简报已经体现过，就不再重复

所以必须存一份“本次简报覆盖了哪些事件”的结构化数据，不能只保存最后生成的纯文本。

### 6.4 数据结构建议

当前 [hourly_digest.py](/Users/shuhuaiwang/personal-info-monitor/backend/app/models/hourly_digest.py) 只有：

- `title`
- `summary`
- `content_count`
- `sources`

建议新增一类结构化字段，例如：

- `metadata_` JSON

其中保存：

- `event_keys`
- `top_cluster_titles`
- `selected_content_ids`
- `generation_provider`
- `generation_model`

注意：当前项目没有成熟 migration 体系，涉及 schema 变更时要同步安排一个轻量升级方案。

## 7. 模型抽象改造

### 7.1 目标

把当前分散在多个文件里的 provider 逻辑收口。

### 7.2 建议目录

建议新增：

- `backend/app/ai/base.py`
- `backend/app/ai/providers/openai_provider.py`
- `backend/app/ai/providers/ollama_provider.py`
- `backend/app/ai/translation_service.py`
- `backend/app/ai/hourly_digest_service.py`

### 7.3 接口建议

最小接口：

- `translate(text, target_language) -> str | None`
- `generate_digest(payload) -> str | None`
- `available() -> bool`
- `describe() -> dict`

### 7.4 现有代码迁移方向

- [translator.py](/Users/shuhuaiwang/personal-info-monitor/backend/app/processors/translator.py) 逐步转为 use case 封装，底层 provider 逻辑迁出
- [summarizer.py](/Users/shuhuaiwang/personal-info-monitor/backend/app/processors/summarizer.py) 不再承担抓取入库阶段职责
- [hourly_digest_tasks.py](/Users/shuhuaiwang/personal-info-monitor/backend/app/tasks/hourly_digest_tasks.py) 只负责调度和数据库读写，不直接写 provider 调用细节

## 8. 信源上限设计

### 8.1 建议默认值

建议默认：

- `max_sources = 200`

### 8.2 生效位置

必须双重控制：

- 前端创建 source 时提示并阻止继续添加
- 后端 `POST /api/sources` 和 bulk import 强校验

### 8.3 配置方式

加入系统设置，例如：

- `limits.max_sources`

后续可以扩展：

- `limits.max_fetch_concurrency`
- `limits.max_digest_candidates`
- `limits.max_hourly_digest_input_items`

## 9. 分阶段实施计划

### Phase 1. 解耦抓取与翻译

目标：

- 入库不再调用翻译模型
- reader 保留按需翻译

任务：

- 修改 `ContentProcessor.process()`，停止写入 `translated_title` / `translated_summary`
- 整理 reader 按需翻译逻辑
- 前端阅读页明确“看译文”交互
- 补回归测试：抓取时不触发模型调用

### Phase 2. 重构小时简报 pipeline

目标：

- 小时报彻底变成独立 AI 定时任务
- 规则筛选先行，模型只处理候选集

任务：

- 调整 `hourly_digest_tasks.py`
- 在 `RankingService` 上加入：
  - 多信源优先
  - 长文优先
  - 已覆盖事件降权或剔除
- 保存事件指纹
- 明确“无模型则不生成简报”

### Phase 3. 收口 provider 抽象

目标：

- OpenAI / Ollama provider 解耦
- 后续 CLI / agent 可统一查询模型状态

任务：

- 引入 `ModelProvider` 抽象
- 拆分 `TranslationService` / `HourlyDigestService`
- 统一模型 availability 检测

### Phase 4. 上限与配额治理

目标：

- 控制系统规模
- 避免 source 数和 digest 输入无限增长

任务：

- 后端增加 source 上限校验
- 前端增加上限提示
- 增加 digest 输入条数上限
- 为 CLI 暴露相关配置查看接口

## 10. 优先级建议

建议执行顺序：

1. 先做翻译按需化
2. 再改小时简报去重与最小排序策略
3. 然后抽离 provider 层
4. 最后补 source 上限与预算控制

原因：

- 第 1 步能最快消除抓取与模型速度冲突
- 第 2 步能直接提升小时简报质量
- 第 3 步是结构性收益
- 第 4 步是稳定性治理

## 11. 验收标准

### 翻译

- 抓取批处理中不再发生翻译模型调用
- 用户点击“看译文”才触发翻译
- 同一内容二次打开复用缓存结果

### 简报

- 整点任务只在模型可用时运行
- 同主题多信源内容在简报中被合并
- 上一轮已覆盖事件不会在下一轮重复出现
- 简报正文为目标语言段落式文本，并附原始链接

### 系统

- 无模型配置时，抓取/检索/阅读仍正常
- 无模型配置时，不生成简报
- source 超过上限时后端会拒绝创建

