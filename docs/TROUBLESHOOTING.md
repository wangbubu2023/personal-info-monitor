# Troubleshooting

## 评分与排序异常

- 词表/规则变更后需 **重启后端**，并对历史内容跑批量重打分：`backend/scripts/rescore_contents.py`（详见 [SCORING_MODEL.md](./SCORING_MODEL.md) §6）
- 无 `final_score`：检查 `metadata.fetch_acceptance` 是否为 `incomplete`
- 促销/订阅类文章分数虚高：检查摘要是否含通讯 boilerplate；finish 路径会调用 `summary_clean.py` 清洗

## 服务无法启动

1. 运行 `./pim logs`
2. 检查 `backend/.venv` 是否存在
3. 检查 `backend/.env` 与 `~/.pim/data/runtime-secrets.json`
4. 手动访问 `http://127.0.0.1:8000/livez`

## API Key 认证失败

- 使用 `./pimctl auth whoami` 检查当前 profile
- 重新执行 `./pimctl auth login --server http://127.0.0.1:8000 --api-key <key>`
- 若本地 `.env` 为空，PIM 会优先使用 `runtime-secrets.json`

## 浏览器会话验证失败

- 先确认目标站点没有验证码或强制登录挑战
- 检查 Playwright profile 目录是否可写
- 查看后端日志中的 `configs_browser` 相关错误
- VPS / Linux 容器里做 X 登录时，必须有可视化显示环境：设置 `DISPLAY` / `WAYLAND_DISPLAY`，
  或用 `xvfb-run` / 系统级 Xvfb 启动 PIM。X 登录不能依赖纯 headless 浏览器完成。

## 分类/仪表盘数据看起来延迟

- 分类树和 Dashboard 统计增加了短 TTL 内存缓存
- 默认几十秒内可能看到旧值
- 稳定性优先于“每次请求都打满数据库”

## 原子库无数据 / API 404

- 确认 `backend/.env` 中 `ATOMS_ENABLED=true` 并已重启服务
- `pimctl atoms stats --json` 查看总量
- P0 阶段需手工 `POST /api/atoms` 或 CLI 录入；自动 LLM 提取在 P1
- 自动提取依赖系统设置中启用 Atoms、配置可用模型，且未开启 AI 全局暂停或 `PIM_AI_HARD_DISABLE`
- 历史回填：`pimctl atoms backfill --limit 200 --since 2026-01-01`

## 跨文关系无数据 / 误判

- 关系推断需 `ATOMS_RELATIONS_ENABLED=true` 且已重启服务
- 仅对 **信息**、**数据** 类原子自动推断；观点类不参与
- 候选规则：跨文章、同 domain、entity 有交集、时间窗 ±30 天（或同一 period 字符串）
- 新关系默认未验证；前端「关联原子」Tab 或 `pimctl atoms relations verify` 确认印证
- 全库重跑：`pimctl atoms relations reconcile --limit 1000`（低峰执行，依赖 LLM 配额）
- 关系过多：单原子最多自动写入 5 条；可删除误报：`DELETE /api/atom-relations/{rel_id}`
- reconcile 慢：属正常，用 `pimctl atoms relations reconcile-status <job_id>` 查看进度

## 需要回滚或备份

- 备份：`./pim backup`
- Alembic 回滚：`./pim rollback <revision>`
