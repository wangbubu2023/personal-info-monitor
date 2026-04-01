# Troubleshooting

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

## 分类/仪表盘数据看起来延迟

- 分类树和 Dashboard 统计增加了短 TTL 内存缓存
- 默认几十秒内可能看到旧值
- 稳定性优先于“每次请求都打满数据库”

## 需要回滚或备份

- 备份：`./pim backup`
- Alembic 回滚：`./pim rollback <revision>`
