# Stream 3: CI + 文档 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 GitHub Actions CI（后端测试 + 前端测试/lint/audit + 安全扫描），补充三篇 ADR 记录关键设计决策，新增贡献指南。

**Architecture:** 三个并行 CI job 覆盖全部质量门禁；ADR 遵循项目现有格式；CONTRIBUTING.md 作为新成员入口。

**Tech Stack:** GitHub Actions, Python, Node.js, pip-audit

---

### Task 1: `.github/workflows/ci.yml`

**Files:**

- Create: `.github/workflows/ci.yml`
- **Step 1: 创建 `.github/workflows/` 目录并写入 `ci.yml`**

Create `.github/workflows/ci.yml` with the following content:

```yaml
name: CI

on:
  push:
    branches:
      - main
      - master
  pull_request:
    branches:
      - main
      - master

jobs:
  backend:
    name: Backend Tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.14"

      - name: Install uv
        run: pip install uv

      - name: Install dependencies
        run: cd backend && uv sync

      - name: Run pytest with coverage
        run: cd backend && ./.venv/bin/pytest -q --cov=app --cov-fail-under=60

  frontend:
    name: Frontend Lint, Test & Audit
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: "npm"
          cache-dependency-path: frontend/package-lock.json

      - name: Install dependencies
        run: cd frontend && npm ci

      - name: Lint
        run: cd frontend && npm run lint

      - name: Test
        run: cd frontend && npm test

      - name: Audit production dependencies
        run: cd frontend && npm audit --omit=dev

  security:
    name: Backend Security Scan
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.14"

      - name: Install pip-audit
        run: pip install pip-audit

      - name: Run pip-audit
        run: cd backend && pip-audit
```

**验证步骤：**

选项 A — 使用 `act` 在本地模拟 GitHub Actions（需先安装 `act`）：

```bash
# 测试单个 job
act -j backend
act -j frontend
act -j security

# 测试完整工作流
act push
```

选项 B — 直接推送触发：

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions CI workflow"
git push origin main
```

推送后在仓库的 Actions tab 查看三个 job 是否全部通过。

---

### Task 2: `docs/ADR-002-digest-time-field.md`

**Files:**

- Create: `docs/ADR-002-digest-time-field.md`
- **Step 1: 创建 ADR-002**

Create `docs/ADR-002-digest-time-field.md` with the following content:

```markdown
# ADR-002: 统一使用 fetched_at 作为 Digest 时间过滤字段

## 状态

已实施（2026-04-01）

## 背景

代码审计发现 Digest 相关两处实现使用了不同的时间字段进行过滤：

- `api/digest.py`（用于 UI 展示的 Digest 接口）使用 `fetched_at`
- `digest_service.py`（用于邮件简报生成的服务层）使用 `publish_time`

这导致 UI 与邮件 digest 对同一时间段内容的口径不一致——当某条内容 `publish_time` 为空或为未来时间时，两者返回的条目集合会产生差异，造成用户困惑。

约 10% 的内容 `publish_time` 为 null 或未来时间（上游数据质量问题）。

## 决策

统一使用 `fetched_at` 作为 Digest 的时间过滤字段，应用于所有 Digest 相关查询路径（UI 接口、邮件简报服务、CLI 输出）。

## 原因

- `fetched_at` 是系统在抓取时写入的字段，由 PIM 自身控制，保证不为空、不出现未来时间。
- `publish_time` 依赖上游数据质量，约 10% 的内容该字段为 null 或未来时间，过滤结果不可靠。
- 数据库已存在 `ix_content_fetched_at` 索引，以 `fetched_at` 过滤的范围查询可充分利用该索引，无需额外迁移。
- 统一字段后，UI 展示与邮件 digest 内容口径一致，消除用户困惑。

## 替代方案

**使用 `publish_time`（已否决）**

原因：约 10% 的内容 `publish_time` 为 null 或未来时间，导致过滤结果不完整或不一致。修复上游数据质量的成本高且不可控，而 `fetched_at` 已能满足"最近抓取内容"的语义需求。

## 结果与权衡

优点：

- UI 与邮件 digest 内容口径完全一致
- 查询利用已有索引，性能不退化
- 系统对上游 publish_time 数据质量不敏感

代价：

- `fetched_at` 语义是"系统抓取时间"而非"内容发布时间"，在极端情况下（抓取严重滞后）可能与用户预期的发布时间有偏差
- 若未来需要按发布时间过滤，需另行处理 null 和未来时间的边界情况
```

**验证步骤：**

```bash
# 确认文件创建成功
ls docs/ADR-002-digest-time-field.md

# 确认格式与 ADR-001 一致（对比标题结构）
head -5 docs/ADR-001-local-monolith.md
head -5 docs/ADR-002-digest-time-field.md
```

---

### Task 3: `docs/ADR-003-auth-credentials.md`

**Files:**

- Create: `docs/ADR-003-auth-credentials.md`
- **Step 1: 创建 ADR-003**

Create `docs/ADR-003-auth-credentials.md` with the following content:

```markdown
# ADR-003: 凭据存储演进策略

## 状态

阶段 1 已实施（2026-04-01）；阶段 2 在 Stream 4 中实施；阶段 3 远期规划。

## 背景

PIM 需要在客户端安全存储 API Key，同时兼顾两种运行模式：

- **Web 模式**：用户通过浏览器访问本地 FastAPI 服务（`http://127.0.0.1:8000`），单用户场景
- **Tauri 模式**：原生桌面壳层，调用同一本地 FastAPI 服务，可访问操作系统 Keychain

不同运行模式的安全边界和可用的存储机制不同，需要分阶段演进。

## 决策

凭据存储分三个演进阶段：

### 阶段 1（当前，已实施）

| 运行模式 | 存储位置 | 说明 |
|---------|---------|------|
| Web 模式 | `localStorage` | 本地单用户场景，浏览器同源隔离已足够 |
| Tauri 模式 | `app_config/secrets/pim_api_key` 文件，权限 `0o600` | 明文文件，仅当前用户可读 |

### 阶段 2（近期，Stream 4 实施）

- **Tauri 模式**：迁移到操作系统 Keychain（使用 `keyring` crate），不再写入明文文件
- **Web 模式**：保持 `localStorage` 不变（本地单用户，无更高安全需求）

### 阶段 3（远期，仅 VPS 多用户场景）

- 引入多用户令牌体系，服务端签发短期 JWT，客户端不持久化 API Key 原文
- 仅在 PIM 部署为多用户 VPS 服务时触发此阶段评估

## 原因

- 阶段 1 实现简单，覆盖当前单用户本地场景，无额外依赖
- 阶段 2 的 Keychain 集成提升 Tauri 模式安全性，避免 API Key 以明文落盘，且 `keyring` crate 已是 Tauri 生态标准做法
- Web 模式始终面向本地单用户，`localStorage` 的同源隔离在此场景下足够，不必过度工程化
- 阶段 3 仅在真正出现多用户 VPS 需求时才触发，避免过早引入复杂度

## 替代方案

**所有模式统一使用加密文件（已否决）**

原因：Tauri 模式完全可以利用操作系统 Keychain，没有理由绕过它。加密文件仍需管理加密密钥本身的存储，问题没有根本解决。

**阶段 1 直接使用 Keychain（已否决）**

原因：Web 模式无法访问操作系统 Keychain；Tauri 模式阶段 1 以 0o600 文件过渡，实现成本低，可快速交付。

## 结果与权衡

优点：

- 分阶段演进，每阶段都有明确安全边界和实现范围
- 避免过早引入不必要的复杂度
- Tauri 模式阶段 2 迁移后安全性达到操作系统级别

代价：

- 阶段 1 的 Tauri 模式 API Key 明文落盘（0o600 缓解，但仍非最优）
- 阶段 2 引入 `keyring` crate 依赖，需处理 Linux headless 环境下 Keychain 不可用的边界情况

## 触发重评估的条件

- PIM 需要支持多用户共享同一服务实例 → 触发阶段 3 评估
- Tauri 模式需支持 Linux headless 环境 → 需评估 `keyring` crate 的 fallback 策略
```

**验证步骤：**

```bash
# 确认文件创建成功
ls docs/ADR-003-auth-credentials.md
```

---

### Task 4: `docs/ADR-004-feature-flags.md`

**Files:**

- Create: `docs/ADR-004-feature-flags.md`
- **Step 1: 创建 ADR-004**

Create `docs/ADR-004-feature-flags.md` with the following content:

```markdown
# ADR-004: Feature Flags 单一事实源策略

## 状态

已记录（2026-04-01），待实施。

## 背景

当前项目中 Feature Flags 在前后端各维护一份：

- 后端：`backend/app/features.py`，定义 `PODCAST_SOURCES_ENABLED`、`KEYWORD_MONITORING_ENABLED` 等标志
- 前端：`frontend/src/features.ts`，独立维护相同标志的副本

这导致两个问题：

1. **同步风险**：修改一侧时容易遗漏另一侧，导致 UI 显示与后端行为不一致
2. **双重维护负担**：每次新增 Feature Flag 都需要在两处同步修改

## 决策

**目标状态（下一迭代实施）**：后端作为 Feature Flags 的单一事实源，前端在应用启动时通过 `GET /api/config/features` 读取当前 Flag 状态，不再本地维护副本。

**过渡期策略（当前）**：保持前后端双份定义，但通过 CI 检查确保双份一致，防止静默漂移。

## 实施路径

### 过渡期（当前已生效）

- CI 中增加一致性检查脚本，比对 `backend/app/features.py` 与 `frontend/src/features.ts` 中的 Flag 名称集合
- 若发现不一致，CI 失败并输出差异，强制人工对齐

### 目标状态（下一迭代）

1. 后端新增端点：`GET /api/config/features`，返回当前所有 Feature Flags 的键值对（JSON）
2. 前端启动时调用该端点，将结果存入 React Context / Zustand store
3. 前端原有 `features.ts` 中的静态定义全部移除
4. 更新前端所有引用 Feature Flag 的代码，改为从 Context/Store 读取
5. CI 一致性检查脚本随之退役

## 原因

- 单一事实源消除同步风险，减少人为错误
- 后端已具备运行时读取环境变量的能力，天然适合作为 Flag 源
- 过渡期保留双份 + CI 检查，确保现有功能不受影响，迭代风险可控

## 替代方案

**前端作为单一事实源（已否决）**

原因：后端功能的启用/禁用应由服务端控制，前端作为展示层不应承担此职责；且后端无法读取前端的 Flag 定义。

**维持双份，不做任何约束（已否决）**

原因：无约束的双份定义已造成实际漂移问题，审计报告中已发现不一致项。

**直接删除前端副本，强制同步实施（已否决）**

原因：需要同时实现后端端点、前端数据获取逻辑和全量引用替换，变更范围过大，拆成两步更稳妥。

## 结果与权衡

优点：

- 过渡期通过 CI 防止静默漂移，无需立刻重构
- 目标状态下 Feature Flag 管理完全收敛到后端，前端零维护负担
- `/api/config/features` 端点未来可扩展为支持 per-user Feature Flag

代价：

- 过渡期仍需双份同步，CI 检查只能防止漂移，不能完全消除维护负担
- 目标状态引入了前端启动时的一次额外 API 调用（可通过缓存或与其他初始化请求合并缓解）

## 触发重评估的条件

- Feature Flags 数量超过 10 个 → 考虑引入专用 Feature Flag 服务
- 需要 per-user 或 per-tenant 的动态 Flag → 需在 `/api/config/features` 中引入身份感知逻辑
```

**验证步骤：**

```bash
# 确认文件创建成功
ls docs/ADR-004-feature-flags.md

# 确认四篇 ADR 均存在
ls docs/ADR-00*.md
```

---

### Task 5: `docs/CONTRIBUTING.md`

**Files:**

- Create: `docs/CONTRIBUTING.md`
- **Step 1: 创建 `docs/CONTRIBUTING.md`**

Create `docs/CONTRIBUTING.md` with the following content:

```markdown
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

详见 `[docs/LOCAL_RUN.md](LOCAL_RUN.md)`。

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

- `cd backend && ./.venv/bin/pytest -q` 通过
- `cd frontend && npm test` 通过
- `cd frontend && npm run lint` 通过（零警告）
- `cd frontend && npm audit --omit=dev` 无高危漏洞

## 分支命名规范


| 前缀       | 用途       | 示例                      |
| -------- | -------- | ----------------------- |
| `feat/`  | 新功能      | `feat/hourly-digest-ui` |
| `fix/`   | Bug 修复   | `fix/digest-time-field` |
| `chore/` | 工程/依赖/文档 | `chore/update-axios`    |


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


| Job        | 内容                          |
| ---------- | --------------------------- |
| `backend`  | pytest + 覆盖率检查（≥60%）        |
| `frontend` | ESLint + Vitest + npm audit |
| `security` | pip-audit 后端依赖安全扫描          |


**PR 合并前所有 job 必须全绿。**

CI 工作流定义见 `[.github/workflows/ci.yml](../.github/workflows/ci.yml)`。

```

**验证步骤：**

```bash
# 确认文件创建成功
ls docs/CONTRIBUTING.md

# 预览文件结构（确认各节均存在）
grep "^##" docs/CONTRIBUTING.md
```

---

## 交付物汇总


| 文件                                  | 类型  | 说明                                        |
| ----------------------------------- | --- | ----------------------------------------- |
| `.github/workflows/ci.yml`          | 新建  | 三个并行 CI job：backend / frontend / security |
| `docs/ADR-002-digest-time-field.md` | 新建  | 统一 Digest 时间字段决策记录                        |
| `docs/ADR-003-auth-credentials.md`  | 新建  | 凭据存储三阶段演进策略                               |
| `docs/ADR-004-feature-flags.md`     | 新建  | Feature Flags 单一事实源策略                     |
| `docs/CONTRIBUTING.md`              | 新建  | 新成员贡献入口：环境、测试、分支、PR、CI                    |


## 端到端验证

所有文件创建完成后，执行以下验证：

```bash
# 1. 确认所有文件存在
ls .github/workflows/ci.yml
ls docs/ADR-002-digest-time-field.md
ls docs/ADR-003-auth-credentials.md
ls docs/ADR-004-feature-flags.md
ls docs/CONTRIBUTING.md

# 2. 验证 YAML 语法（需要安装 yamllint 或 python3）
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "YAML OK"

# 3. 可选：使用 act 本地运行 CI
act push --dry-run
```

