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

在提交 PR 前，请确保以下门禁全部通过：

### 1. 后端测试

```bash
cd backend
./.venv/bin/pytest -q
```

覆盖率低于 70% 时 CI 会失败（`--cov-fail-under=70`）。

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

### 4. 前端 E2E

```bash
cd frontend
npm run e2e
```

使用 Playwright 运行 `frontend/e2e/specs` 下的端到端流程测试。首次运行如缺少浏览器，请先执行：

```bash
cd frontend
npx playwright install chromium
```

### 5. 前端依赖安全扫描

```bash
cd frontend
npm audit --omit=dev
```

仅检查生产依赖，开发依赖漏洞不阻断。

### 6. 后端工程纪律门禁

CI 会额外执行以下后端检查，本地修改相关区域时也建议同步运行：

```bash
cd backend
uv run ruff check app
uv run python scripts/check_ble001_budget.py
uv run --with 'vulture>=2.11' python scripts/check_dead_code.py
uv run python scripts/export_openapi.py ../frontend/src/types/openapi.json
git diff --exit-code -- ../frontend/src/types/openapi.json
uv run python scripts/check_domain_imports.py --phase=7
uv run python scripts/check_offline_eval_regression.py
uv run python scripts/check_file_lines.py
```

- `BLE001`：禁止新增盲目吞异常的生产代码债务；预算由 `backend/scripts/ble001_budget.json` 控制，只允许下降或持平。
- `dead-code`：Vulture 死代码预算由 `backend/scripts/dead_code_budget.json` 控制，新增未使用代码会阻断 CI。
- `OpenAPI`：后端接口变更后必须重新导出并提交 `frontend/src/types/openapi.json`；前端还会用 `npm run check:api-types` 校验生成类型。
- `domain boundary`：`scripts/check_domain_imports.py --phase=7` 会阻止跨层/跨域反向依赖，规则背景见 [`docs/MODULE_BOUNDARIES.md`](MODULE_BOUNDARIES.md)。
- `file-lines`：千行大文件行数预算由 `backend/scripts/file_lines_budget.json` 控制，只减不增（见下方「复杂度预算」）。

## 复杂度预算（硬规矩）

单人维护的系统，复杂度是持续税。以下三条与 BLE001 / dead-code 预算同级，PR 审阅时按此执行：

1. **增模块删等量**：每新增一个模块/文件，应在同一 PR 中删除大致等量的旧代码（死代码、废弃路径、被替代的实现）。做不到时在 PR 描述里说明原因。
2. **行数预算只减不增**：`backend/scripts/file_lines_budget.json` 锚定四个千行文件的当前行数（website.py 1583 / pimctl app.py 1702 / pim 1636 / CredentialsTab.tsx 955）。CI 阻止它们继续变长；瘦身后运行 `check_file_lines.py --update` 提交新基线。不强迫专项重构。
3. **一次触碰规则**：功能冻结期内，因修 bug 打开上述大文件时，顺手把所改动的那一块拆出到独立模块——拆你摸到的部分即可，不扩大范围。

## 提交前检查清单

- [ ] `cd backend && ./.venv/bin/pytest -q` 通过
- [ ] `cd frontend && npm test` 通过
- [ ] `cd frontend && npm run lint` 通过（零警告）
- [ ] `cd frontend && npm run e2e` 通过
- [ ] `cd frontend && npm audit --omit=dev` 无高危漏洞
- [ ] 涉及后端接口、领域边界、异常处理或清理代码时，同步运行对应工程纪律门禁

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
- [ ] E2E 通过
- [ ] 工程纪律门禁通过（如涉及后端接口、异常处理、死代码或领域边界）
- [ ] 依赖安全扫描通过
- [ ] 手动验证步骤（如适用）
```

## CI

所有 push 和 PR 会自动触发 GitHub Actions CI，包含三个并行 job：

| Job | 内容 |
|-----|------|
| `backend` | ruff、BLE001 预算、dead-code 预算、OpenAPI、domain boundary、offline eval、requirements 同步、pytest + 覆盖率检查（≥70%） |
| `frontend` | ESLint、OpenAPI 类型生成校验、Vitest、Playwright E2E、npm audit |
| `security` | pip-audit 后端依赖安全扫描 |

**PR 合并前所有 job 必须全绿。**

CI 工作流定义见 [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)。
