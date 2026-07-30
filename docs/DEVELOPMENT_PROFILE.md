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

- 资讯列表：在浏览卡片时快速标记 `必看 / 一般 / 噪音`
- Reader：读完后补充价值、质量、事实密度；Lane 只在分类错误时展开
- Event：查看事件卡时标记 `准确 / 部分准确 / 错误 / 不确定`
- Atom：查看或编辑原子时标记 `有效 / 需修正 / 无效 / 不确定`
- 误合、漏合继续使用 Event 页面已有的反馈入口

普通标注不会进入单独工作台。只有冲突、离线历史样本和跨对象任务，才通过顶部的
`必须集中处理` 数量进入 `/review`。

## 数据语义

- `annotation_tasks`：稳定目标、上下文快照和生成原因
- `annotation_labels`：追加式人工标签；修改会保留被替代记录
- `annotation_adjudications`：冲突的最终裁决；裁决后不可再覆盖
- 阅读、收藏、隐藏是行为信号，不会自动成为 gold label

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
