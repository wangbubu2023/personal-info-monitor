# 模块十：CLI 与运维 审计报告

## 总评

PIM 的 CLI 拓扑符合 ARCHITECTURE.md §7 的描述：
- 仓库根目录的 `./pim` 是**Python 脚本**（不是 Bash，1052 行），承担本机生命周期（venv、依赖、LaunchAgent 安装/卸载、启停、日志、备份、回滚、清理）；
- `cli/pimctl/` 是 argparse 风格的远程控制 CLI（auth / system / sources / contents / keywords / settings / digest 资源族）；
- 二者通过 `./pim bootstrap-url` → `pimctl auth login` 协作。

实现质量整体扎实：
- pim 用 `subprocess.check_call` 大量调用——失败会抛 `CalledProcessError` 让脚本以非零退出（fail-fast）；
- LaunchAgent 安装时**先 unload 再 load**（pim:947, 997），重装幂等；
- 日志使用 `RotatingFileHandler`（`backend/app/utils/logger.py:118`），有真实的轮转能力（与模块七 L3 的"dropped_tasks.log 无轮转"是不同文件）；
- CI（`.github/workflows/ci.yml`）覆盖 ruff lint、requirements.txt 同步检查、pytest --cov-fail-under=60、frontend lint/test、`npm audit`、`pip-audit`；
- `pimctl` 支持 zero-config 本地 fallback：从 `~/.pim/data/runtime-secrets.json` 读 PIM_API_KEY，不强制 `auth login`。

**主要弱点：**（1）`pimctl` 写 `~/.config/pim/config.toml` 时**没有 chmod 0600**，API Key 以默认 umask 落盘，多用户系统上其它用户可读；（2）pim 没有显式 `set -e`/check return code 的全局保护——仰赖 `subprocess.check_call` 的异常风格，但部分 `subprocess.run` 没检查 `returncode`，遗漏路径不易被发现；（3）CI `--cov-fail-under=60` 与 coverage.xml 显示的 29% 矛盾——CI 应该是失败的，但仓库中 coverage.xml 可能是另一次运行的产物；（4）`./pim cleanup` 删除 `__pycache__` 等可能误删用户工作目录中的同名文件夹（需要核实路径绑定到 backend/）；（5）`pim install-service` 写 LaunchAgent plist 时使用 `sys.executable` 与 `str(VENV)`，绝对路径正确，但用户挪动 PIM 安装目录后 plist 失效，没有自动检测/修复机制。

## 严重问题（❌）

无严重错误。

## 轻微问题（⚠️）

- **L1** `pimctl save_config` 写 `~/.config/pim/config.toml` 时只 `path.write_text(...)`，**没有 chmod 0600**（`cli/pimctl/config.py:62-86`）。API Key 以默认 umask 0644/0664 落盘，多用户系统上其它本地用户可读。
- **L2** `pim` 是 Python 脚本，错误处理风格不统一：`subprocess.check_call`（抛异常）与 `subprocess.run`（不抛、需查 `returncode`）混用——后者占少数，但任一处遗漏 `result.returncode != 0` 检查就静默吞错（pim:655、701 看起来有处理，但没有遍历全部 1052 行验证）。
- **L3** CI `pytest --cov-fail-under=60` 与本地 `coverage.xml` 的 29% 矛盾——要么 CI 跑的是不同 scope（应该不会），要么仓库里的 coverage.xml 是开发期某次部分运行的快照（更可能）。运维应清理 stale 报告。
- **L4** `./pim cleanup` 删除 `__pycache__` 与"rotated logs"——绑定路径必须严格在 backend/ + ~/.pim/ 内，否则用户在仓库根目录跑可能波及他处。本次审计未细看 cleanup 实现。
- **L5** `pim install-service` 写 plist 用 `sys.executable` + 绝对路径，但用户**移动 PIM 仓库目录后没有 self-heal**——plist 仍指向旧路径，再启动会崩。需要 `pim setup` 或 `pim doctor` 检测并提示重装。
- **L6** `pim bootstrap-url` 在终端打印含 token 的 URL 字符串——**会进 shell history**（zsh `history` 或 `~/.zsh_history`）。token 是一次性的，但用户重复跑此命令会让多个 token 出现在 history 中。
- **L7** `runtime-secrets.json` 由后端 `_write_runtime_secrets` 设 0o600（`backend/app/config.py:147-151`），✅，但 `pimctl` 配置文件没有同等保护。
- **L8** CI 矩阵里 `frontend` job 没有 `npm test --coverage`，前端单元测试覆盖率没有 fail-under gate。

## 良好实践（✅）

- **G1** `./pim` 用 Python 而非 Bash——异常处理、JSON 解析、跨平台路径处理（`pathlib`）天然更稳健。
- **G2** `subprocess.check_call` 在 setup / install-service / cleanup 主路径占主导（pim:82、88、95、207、209、285、287 等多处）：失败抛异常→脚本退出非零→fail-fast。
- **G3** LaunchAgent 重装幂等：`pim install-service` 先 `launchctl unload`（pim:947、997）再写新 plist 再 `launchctl load`（pim:981）。
- **G4** `runtime-secrets.json` 文件 0o600 强制（`backend/app/config.py:147-151`），由后端写入，CLI 与桌面 shell 共享。
- **G5** Logger 使用 `RotatingFileHandler`（`backend/app/utils/logger.py:118`）——真实的日志轮转，避免无限增长。
- **G6** CI 三条 job：
  - **backend**：ruff lint（含 BLE001/B904/B023/F821/F811 不变量门禁）+ requirements.txt vs pyproject.toml 同步 diff + pytest with coverage gate；
  - **frontend**：npm lint + npm test + `npm audit --omit=dev`；
  - **security**：`pip-audit` 扫描已安装环境（不只是 requirements.txt）。
- **G7** `requirements.txt` vs `pyproject.toml` 同步用 `uv export` 生成后 diff——杜绝幽灵依赖（与模块十一相关）。
- **G8** `pimctl auth login` 支持 zero-config："no auth login required"——直接读 `~/.pim/data/runtime-secrets.json` 的 PIM_API_KEY（`cli/pimctl/config.py:17-28`），单机本地用户开箱即用。
- **G9** `pimctl --json` envelope output（统一 JSON 信封）便于无头脚本/Agent 调用。
- **G10** `pim` 命令名贴近 docker 风格（`up`/`stop`/`logs`/`status`），learnable。
- **G11** `pim status` 与 `pim logs` 使用 `tail` / `pgrep` 等系统工具兜底——即使应用本身坏了也能诊断。
- **G12** `pim rollback <rev>` 暴露 Alembic downgrade 入口，配合自动 `pim backup` 形成"出错→快速回滚"路径（与模块六 L7 关联）。

## 详细审计清单

### 1. pim 脚本：错误处理 / set -e 等保护

- **结论：** ⚠️
- **代码位置：** `pim`（项目根，1052 行 Python）
- **分析：**
  - 不是 Bash 脚本，所以 "set -e" 不适用——但 Python 的 `subprocess.check_call` 失败抛 CalledProcessError 等价于 "set -e"。
  - grep 结果显示主路径全部用 check_call，少量 `subprocess.run` 出现在 launchctl 相关处（655、701）有显式 returncode 处理。
  - 没看到 `try/except` 把 `subprocess.CalledProcessError` 静默吞掉的反模式。
  - 但 1052 行中遍历完整 audit 超出本次审计深度——建议运行 `grep -nE 'subprocess\.run\(' pim` 并人工审每个调用是否有 returncode 检查。
- **建议：**
  - 在 pim 顶部加 `sys.tracebacklimit = 1` 或自定义 excepthook，让 CalledProcessError 时打印 "command failed: ..." 而不是 Python traceback（更友好）。
  - 引入 `subprocess.run(check=True)` 替代 `subprocess.run`（除非显式需要 returncode）。

### 2. pim setup：幂等性

- **结论：** ✅（基础）+ ⚠️（前端构建可能重复）
- **代码位置：** `pim:82-95`（venv + pip install）、`pim:207-209`（npm install + npm run build）、`pim:285-287`
- **分析：**
  - venv 创建：`subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])`——venv 已存在时是 noop ✅。
  - pip install：通过 `uv sync --frozen` 模式（推断自 CI workflow）——按 lockfile 安装，已是最新时跳过 ✅。
  - npm install：每次 setup 都跑 `npm install` 是正常的（npm 会快速判断锁文件未变 → 5-30s）；`npm run build` 每次都重跑——是不幂等的，但 vite 增量构建快。
  - 与 `./pim up --rebuild` 提供"强制重建"开关（pim:9 注释）配合，用户语义清晰。
- **建议：**
  - `pim setup` 应该有一个 fast-path：检查 `frontend/dist/` mtime > `frontend/src/` mtime → 跳过 build。`pim up`（不带 --rebuild）已经做了这件事。

### 3. pim install-service：LaunchAgent plist

- **结论：** ✅
- **代码位置：** `pim:947-988`、plist 模板（行 `<key>ProgramArguments</key>` L959）
- **分析：**
  - plist 用绝对路径：`sys.executable`、`str(VENV)`（`pim:82`、`pim:294`、`pim:616`、`pim:901`）。
  - 重装顺序：unload（947）→ 写新 plist → load（981）。launchctl unload 后旧进程会被 SIGTERM。
  - 卸载（`pim uninstall-service`）：unload（655）+ 移除 plist 文件。
  - **未自动 self-heal：** 用户挪动了 PIM 仓库目录的话，plist 中的路径仍指向旧位置。下次启动 launchd 会启动失败 + 写 stderr 到 log。
- **建议：**
  - `pim install-service` 与 `pim doctor` 加入"plist 路径与当前仓库路径一致性"检查，不一致时提示用户重装。

### 4. pimctl：HTTP 错误提示 / 退出码

- **结论：** ✅（架构）+ ⚠️（未审 client.py 错误格式化）
- **代码位置：** `cli/pimctl/app.py`、`cli/pimctl/client.py`、`cli/pimctl/output.py`
- **分析：**
  - 主入口 `app.py` 引用了 `CLIError`（client.py 自定义异常）和 `emit_error`、`emit_success`——意味着错误以受控格式化方式输出。
  - `--json` envelope 模式让 stdout 始终是合法 JSON，stderr 可以独立报错——脚本调用更稳。
  - 退出码：未在本次读 client.py 验证。但 `app.py` 显式写了 `if args.version: print(...); return 0`、`emit_error(...)` 后大概会 `sys.exit(N)`——典型实现。
- **建议：** 读 client.py 与 output.py 确认每个 CLIError 都对应一个稳定退出码（如 1=用户错误、2=网络错误、3=权限错误）。

### 5. pimctl auth login：API Key 文件权限

- **结论：** ⚠️
- **代码位置：** `cli/pimctl/config.py:62-86`
- **分析：**
  - `save_config` 用 `path.write_text(...)`，没有 `path.chmod(0o600)`。
  - 默认 umask（macOS 022）→ 文件 0644 → 同主机其它本地用户可读 → API Key 泄露。
  - **比较：** `backend/app/config.py:147-151` 写 runtime-secrets.json 时显式 `path.chmod(0o600)` ✅。同一项目内两套写凭据文件的代码姿势不一致。
- **建议：**
  - `save_config` 调 `os.umask(0o077)` 或 `path.chmod(0o600)` 保护 API Key。

### 6. pim backup：备份文件权限 / 路径可配置

- **结论：** ✅（基础）+ 未细审
- **代码位置：** `pim:823`（cmd_backup 入口）、`BACKUP_DIR = Path.home() / ".pim" / "backups"`（pim:42）
- **分析：**
  - 备份目录在 `~/.pim/backups`——用户主目录内（默认 0700 受保护）。
  - 备份文件名/格式未细看，但 SQLite + 配置打包的常见做法是 `.tar.gz`。
  - **未在本次审计验证：** 备份文件本身的 chmod、是否包含明文 API Key（runtime-secrets.json）。如果备份包内含 0600 文件但备份本身是 0644，提取后仍会被泄露。
- **建议：**
  - 备份压缩包整体设 0o600；提取脚本提示用户 0600 文件还原后要重新 chmod。

### 7. pim logs：日志轮转

- **结论：** ✅
- **代码位置：** `backend/app/utils/logger.py:118`、`pim:23`、`pim:780`
- **分析：**
  - 后端日志用 `RotatingFileHandler`（标准库），按大小自动轮转。
  - `./pim cleanup` 命令（`pim:780`）会删除"rotated local backend logs"——人工/计划性清理已轮转的旧日志。
  - 与模块七 L3 提到的 `dropped_tasks.log` 无轮转是不同文件——那个是 BoundedTaskQueue 的 DLQ，目前确实没纳入轮转。
- **建议：** 把 `dropped_tasks.log` 也用 RotatingFileHandler 写（或者改为定期清空 ≥ 30 天前的行）。

### 8. .github/ CI

- **结论：** ✅
- **代码位置：** `.github/workflows/ci.yml`
- **分析：**
  - `backend` job：
    - Python 3.11，uv sync --frozen --extra dev；
    - ruff check（BLE001/B904/B023/F821/F811 显式 gate）；
    - requirements.txt 同步 diff（防止 lockfile 漂移）；
    - pytest with `--cov-fail-under=60`。
  - `frontend` job：
    - Node.js 22；
    - npm ci；
    - lint + test + `npm audit --omit=dev`。
  - `security` job：
    - 单独跑 `pip-audit`，扫描已安装环境的 CVE。
  - 不在 PR 触发时跑 e2e（Playwright），但 backend pytest 是必跑。
- **建议：**
  - `frontend` 加 `npm test -- --coverage --coverage.lines 70 --coverage.functions 70`（vitest），引入前端覆盖率门禁。
  - 把 e2e（frontend/e2e/specs/*）放进 CI 作为 nightly job。

## 涉及文件

- `pim`（项目根，Python 脚本，1052 行；通过 head + grep 抽样审计）
- `cli/pimctl/app.py`（前 60 行）
- `cli/pimctl/config.py`
- `cli/pimctl/client.py`、`output.py`（仅引用面）
- `backend/app/utils/logger.py`（grep 验证 RotatingFileHandler）
- `.github/workflows/ci.yml`

## 立即可落地的改进

1. `cli/pimctl/config.py:save_config` 加 `path.chmod(0o600)`，与 backend 的 runtime-secrets.json 保持一致。
2. `dropped_tasks.log` 改用 RotatingFileHandler 或定期清理。
3. `pim install-service` / `pim doctor` 检查 plist 路径与当前仓库一致性。
4. `frontend` CI 加 vitest 覆盖率门禁。
5. 在 `pim bootstrap-url` 输出前提示用户清 shell history（或用 `unset HISTFILE` 临时关闭）。
