# Development Profile：消费即标注

`dev` 是代码集成分支，`PIM_RUNTIME_PROFILE=development` 是运行行为。两者不硬编码绑定；
同一提交合并到 `main` 后会默认使用 `production`，标注接口 fail-closed。

## 启动

```bash
git switch dev
git pull --ff-only origin dev
./pim dev
```

打开 `http://127.0.0.1:3000`。顶部出现 `Development Profile` 状态条即表示运行正确。

## 日常标注

- 资讯列表与 Reader：正式的 `重要 / 不重要` 就是价值判断；未操作自然表示一般，不额外显示“一般”
- Reader：当前内容 Tag 会直接外显，可在阅读时调整 1–4 个；后台保留首个 Tag 兼容 Lane
- Reader：读完后可补充内容质量与格式质量，均使用 `高 / 中 / 低`
- Event：使用页面已有的误合、漏合反馈；它们会同步形成 Event 正确性标签
- Atom：编辑并保存表示“需要修正”，标记已验证表示“有效”，不再重复询问原子是否可用

普通标注不会进入单独工作台。只有冲突、离线历史样本和跨对象任务，才通过顶部的
`必须集中处理` 数量进入 `/review`。

## 数据语义

- `annotation_tasks`：稳定目标、上下文快照和生成原因
- `annotation_labels`：追加式人工标签；修改会保留被替代记录
- `annotation_adjudications`：冲突的最终裁决；裁决后不可再覆盖
- 收藏（重要）、隐藏（不重要）、Event 误合/漏合和 Atom 编辑/核验是明确的正式操作，
  在 development profile 会同步形成可导出的显式人工标签
- 取消重要会撤回对应任务；未操作不会写入 `ok`，因此不会把普通浏览误当成人工标签
- 内容 Tag 调整写入 `content_tags`；内容/格式质量分别写入
  `content_quality`、`content_format_quality`

## 导入已有待处理队列

```bash
cd backend
uv run python scripts/import_annotation_review_queues.py
uv run python scripts/import_annotation_review_queues.py --apply
```

脚本读取 `~/.pim/data/eval/gold/review_queues/`，可重复运行，不会创建重复任务。

## 导出评测资产

```bash
cd backend
uv run python scripts/export_annotation_eval.py
```

默认输出：

- `~/.pim/data/eval/gold/annotation_eval_latest.jsonl`
- `~/.pim/data/eval/gold/annotation_eval_latest_manifest.json`

显式 inline label 可以进入导出；存在冲突的任务必须先裁决。Manifest 记录 commit、hash、
任务类型分布和确定性 train/validation/test split。
