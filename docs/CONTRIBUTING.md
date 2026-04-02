# 贡献指南

## 环境要求

| 工具 | 最低版本 | 说明 |
|------|---------|------|
| Python | 3.14+ | 后端运行时 |
| Node.js | 22+ | 前端构建与测试（CI 使用 22 LTS） |
| npm | 随 Node 22 附带 | 前端包管理 |
| uv | 最新稳定版 | 后端 Python 依赖管理（`pip install uv`） |

> 本地开发可使用 Node 25，但 CI 固定在 Node 22 LTS 以保证稳定性。

## 本地启动

详见 [`docs/LOCAL_RUN.md`](LOCAL_RUN.md)。

快速路径：

```bash
# 一键初始化（创建 .venv、安装前后端依赖、生成 .env 模板）
./pim setup

# 启动开发服务器（前端 :3000，后端 :8000）
./pim start
```

## 测试矩阵

在提交 PR 前，请确保以下四项全部通过：

### 1. 后端测试

```bash
cd backend
./.venv/bin/pytest -q
```

覆盖率低于 60% 时 CI 会失败（`--cov-fail-under=60`）。

### 2. 前端测试

```bash
cd frontend
npm test
```

使用 Vitest 运行，输出测试结果摘要。

### 3. 前端 Lint

```bash
cd frontend
npm run lint
```

使用 ESLint，`--max-warnings 0`，任何警告均视为错误。

### 4. 前端依赖安全扫描

```bash
cd frontend
npm audit --omit=dev
```

仅检查生产依赖，开发依赖漏洞不阻断。

## 提交前检查清单

- [ ] `cd backend && ./.venv/bin/pytest -q` 通过
- [ ] `cd frontend && npm test` 通过
- [ ] `cd frontend && npm run lint` 通过（零警告）
- [ ] `cd frontend && npm audit --omit=dev` 无高危漏洞

## 分支命名规范

| 前缀 | 用途 | 示例 |
|------|------|------|
| `feat/` | 新功能 | `feat/hourly-digest-ui` |
| `fix/` | Bug 修复 | `fix/digest-time-field` |
| `chore/` | 工程/依赖/文档 | `chore/update-axios` |

## PR 描述模板

```
## Summary

- 做了什么（bullet points，简洁）
- 解决了什么问题 / 引入了什么功能

## Test Plan

- [ ] 本地后端测试通过
- [ ] 本地前端测试通过
- [ ] Lint 通过
- [ ] 依赖安全扫描通过
- [ ] 手动验证步骤（如适用）
```

## CI

所有 push 和 PR 会自动触发 GitHub Actions CI，包含三个并行 job：

| Job | 内容 |
|-----|------|
| `backend` | pytest + 覆盖率检查（≥60%） |
| `frontend` | ESLint + Vitest + npm audit |
| `security` | pip-audit 后端依赖安全扫描 |

**PR 合并前所有 job 必须全绿。**

CI 工作流定义见 [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)。
