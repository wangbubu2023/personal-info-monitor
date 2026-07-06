# PIM v1.4.0 发布与剩余验收交接

本文用于 v1.4.0 发版后交接人工标注与 VPS 实测。它回答三件事：

1. 500 条人工评测样例从哪里来、怎么标。
2. 4 个真实 offline eval history 点怎么跑。
3. VPS / 付费墙 / X cookie 端到端实测看哪些指标，VPS agent 需要交回什么材料。

## 1. 500 条样例从哪里来，如何标

样例来自 PIM 生产 SQLite 库里的近期内容，默认数据库位置是 `~/.pim/data/pim.db`。导出脚本会读取当前 `backend/.env` / `DATA_DIR` 指向的库，按来源交错抽样，避免 500 条都来自少数高产源。

本地已经跑过一次：从近 30 天开始，自动扩窗到 60 天后导出 500 条，覆盖 76 个源。正式验收仍以你人工确认后的 label 为准，脚本不会自动接受预标建议。

### 1.1 生成候选集

```bash
cd /path/to/personal-info-monitor/backend

./.venv/bin/python scripts/export_eval_candidates.py \
  --output /tmp/pim_eval_candidates_500.jsonl \
  --limit 500 \
  --days 30 \
  --min-records 500 \
  --expand-days-step 30 \
  --max-days 365
```

如果 30 天内容不足，脚本会按 30 天步长扩到最多 365 天。导出的每行是一条 JSON，字段包括 title、summary、full_content 截断片段、source、score metadata 和空的 `label`。

### 1.2 生成预标建议

```bash
./.venv/bin/python scripts/prelabel_eval_candidates.py \
  /tmp/pim_eval_candidates_500.jsonl \
  --output /tmp/pim_eval_candidates_500_prelabeled.jsonl \
  --json
```

预标只写 `suggested_label`、`suggested_confidence`、`suggested_reason`、`review_priority`，不会写正式 `label`。

### 1.3 打开 HTML 审核页

```bash
./.venv/bin/python scripts/review_eval_candidates.py export-html \
  /tmp/pim_eval_candidates_500_prelabeled.jsonl \
  --output /tmp/pim_eval_candidates_500_review.html
```

在浏览器打开 `/tmp/pim_eval_candidates_500_review.html`。逐条确认：

- `must_see`：非常值得进入 Top 20 / 简报核心视野。
- `ok`：相关、可保留，但不是强提醒。
- `noise`：无关、重复、标题党、正文不足、过期或不应进入推荐。

HTML 页支持键盘：`1=must_see`、`2=ok`、`3=noise`、`Backspace=清空`、左右方向键切换。标完后点 `Download TSV` 下载审核表。

也可以直接生成 TSV 并编辑：

```bash
./.venv/bin/python scripts/review_eval_candidates.py export-sheet \
  /tmp/pim_eval_candidates_500_prelabeled.jsonl \
  --output /tmp/pim_eval_candidates_500_review.tsv
```

### 1.4 检查和回填正式 label

```bash
./.venv/bin/python scripts/review_eval_candidates.py --json status \
  /tmp/pim_eval_candidates_500_prelabeled.jsonl \
  --sheet /tmp/pim_eval_candidates_500_review.tsv \
  --require-complete

./.venv/bin/python scripts/review_eval_candidates.py apply-sheet \
  /tmp/pim_eval_candidates_500_prelabeled.jsonl \
  --sheet /tmp/pim_eval_candidates_500_review.tsv \
  --output /tmp/pim_eval_set_500_labeled.jsonl \
  --require-reviewed
```

`status --require-complete` 必须通过：不能有空 label、坏 label、重复 ID 或候选缺行。

### 1.5 安装为正式 eval set

```bash
./.venv/bin/python scripts/validate_eval_set.py \
  /tmp/pim_eval_set_500_labeled.jsonl \
  --min-records 500 \
  --min-sources 30 \
  --install \
  --backup-existing \
  --json
```

安装后目标文件是 `backend/tests/fixtures/eval_set.jsonl`。这一步会备份旧 fixture，并拒绝空标签、非法标签、重复 ID、记录数不足和来源覆盖不足。

## 2. 4 个真实 eval history 点怎么跑

history 默认写到 `~/.pim/data/eval_history.jsonl`。每跑一次 offline eval，脚本追加一行 JSON，包含 `ran_at`、eval set 路径和指标。

```bash
cd /path/to/personal-info-monitor/backend

./.venv/bin/python scripts/run_offline_eval.py --json
./.venv/bin/python scripts/run_offline_eval.py --json
./.venv/bin/python scripts/run_offline_eval.py --json
./.venv/bin/python scripts/run_offline_eval.py --json

./.venv/bin/python scripts/check_eval_history.py \
  --min-points 4 \
  --metric 'precision@20' \
  --compare-to previous \
  --max-drop 0 \
  --json
```

最低门槛是 4 个 history 点且最新 `precision@20` 不低于上一个点。更有意义的跑法是：

1. 在 v1.3.1 的生产库备份上导出 500 条并标注。
2. 用 v1.4.0 当前代码跑第 1 个点，作为发版基线。
3. 升级 VPS 到 v1.4.0 后，在真实运行一轮抓取/简报后跑第 2 个点。
4. 付费墙会话和 X cookie 修复或刷新后各跑 1 个点。

如果必须快速通过 history gate，可以连续跑 4 次；但这只能证明脚本链路，不证明生产趋势。正式验收建议把每次运行的背景写进提交或交接记录。

每周体检邮件会读取同一个 history 文件，并展示最近指标趋势：`precision@20`、`duplicate_rate`、`fulltext_complete_rate`、`source_coverage@20`。

## 3. VPS / 付费墙 / X cookie 端到端实测

VPS agent 的目标不是改代码，而是提供真实运行证据。推荐先升级到 v1.4.0，再按下面命令采集。

### 3.1 升级前先备份和取证

```bash
cd /path/to/personal-info-monitor

./pim backup
git rev-parse HEAD
git describe --tags --always
./pimctl --version
./pim status
./pimctl system health-check --json > /tmp/pim_vps_health_before.json
./pimctl sources list --json > /tmp/pim_vps_sources_before.json
./pimctl contents list --json > /tmp/pim_vps_latest_contents_before.json
```

如果 VPS 还在 v1.3.1，这些材料很有用：可以作为升级前基线，特别是已有内容、源配置、长期失败日志和 X/付费墙的旧表现。

### 3.2 升级到 v1.4.0

```bash
cd /path/to/personal-info-monitor
git fetch --tags origin
git checkout v1.4.0
./pim upgrade --server --skip-playwright --no-pull
./pim restart --server
./pimctl --version
./pimctl system health-check --json > /tmp/pim_vps_health_after.json
```

如果部署必须跟随 `main`，也可以 `git checkout main && git pull --ff-only`，但交接报告里要写清楚实际 commit。

### 3.3 跑 20 源 dry-run 实测表

```bash
cd /path/to/personal-info-monitor/backend

KEY=$(python3 - <<'PY'
import json, pathlib
print(json.loads(pathlib.Path.home().joinpath(".pim/data/runtime-secrets.json").read_text())["PIM_API_KEY"])
PY
)

./.venv/bin/python scripts/run_fetch_field_test.py \
  --server http://127.0.0.1:8000 \
  --api-key "$KEY" \
  --limit 20 \
  --sample-limit 5 \
  --output /tmp/pim_vps_fetch_field_test.md \
  --json-output /tmp/pim_vps_fetch_field_test.json
```

验收重点：

- 总体：`OK / warning / empty / error`，目标是 error 为 0；warning/empty 必须能解释。
- `would-store`：非重复源应有合理数量；如果为 0，要看是否都是 duplicate/stale。
- `diagnostics.normalizer_skip_summary`：重复、过期、正文不足分别是多少。
- `fulltext_status` / `article_fulltext`：付费墙和重点网站是否拿到 full 正文。
- `preferred_strategy`：X 是否走 `graphql`，网站是否走 rss/sitemap/discovery/direct 中预期路径。
- 会话健康：`session_health_status/reason/suggested_action` 是否准确暴露 cookie 过期、paywall、bot wall。

### 3.4 付费墙会话实测

先在本地可信桌面采集会话并同步到 VPS：

```bash
cd /path/to/personal-info-monitor
./pim auth-bundle sync https://example-paywall.com \
  --remote pim@your-vps \
  --remote-pim ~/personal-info-monitor
```

VPS agent 在远端验证：

```bash
./pimctl sources list --json > /tmp/pim_vps_sources_after_auth.json

# 把 <source_id> 换成对应付费墙源 ID
./pimctl sources dry-run <source_id> --sample-limit 5 --json \
  > /tmp/pim_vps_paywall_dry_run.json

./pimctl sources fetch <source_id> --json \
  > /tmp/pim_vps_paywall_fetch_trigger.json
```

验收指标：

- dry-run status 是 `ok` 或可解释 warning。
- samples 中至少有 1 条付费墙内容正文进入 `full_content` 或 metadata 标记 full。
- `session_health_status` 不应是 `expired` / `login_required`；如果是，必须有 `suggested_action`。
- 过期会话应进入 warning channel，并触发去重后的 operator alert。

### 3.5 X cookie 实测

X 默认路径是 `graphql -> rsshub -> nitter`，官方 API 只有单源显式开启时才用。

```bash
./pimctl sources list --json > /tmp/pim_vps_x_sources.json

# 对 3 到 5 个 X 源分别执行
./pimctl sources dry-run <x_source_id> --sample-limit 5 --json \
  > /tmp/pim_vps_x_<handle>_dry_run.json
```

验收指标：

- 有有效 cookie 时，`preferred_strategy` / diagnostics 应显示 GraphQL 或 cookie-first 路径。
- collected / valid / would-store 均合理；低 would-store 要能由 duplicate/stale 解释。
- cookie 缺失或过期时，dry-run 不能静默成功；应写出 `session_health` 和建议动作。
- 不应因为配置了 `X_BEARER_TOKEN` 就自动调用官方 API，除非该源显式设置 `metadata.strategy=api` 或 `metadata.allow_x_api_fallback=true`。

## 4. VPS agent 需要交回的材料

请让 VPS agent 打包以下文件，避免包含明文 cookie、Auth Bundle 或 `runtime-secrets.json`。

```bash
mkdir -p /tmp/pim_v1_4_handoff

cp /tmp/pim_vps_health_before.json /tmp/pim_v1_4_handoff/ 2>/dev/null || true
cp /tmp/pim_vps_health_after.json /tmp/pim_v1_4_handoff/ 2>/dev/null || true
cp /tmp/pim_vps_sources_before.json /tmp/pim_v1_4_handoff/ 2>/dev/null || true
cp /tmp/pim_vps_sources_after_auth.json /tmp/pim_v1_4_handoff/ 2>/dev/null || true
cp /tmp/pim_vps_fetch_field_test.md /tmp/pim_v1_4_handoff/ 2>/dev/null || true
cp /tmp/pim_vps_fetch_field_test.json /tmp/pim_v1_4_handoff/ 2>/dev/null || true
cp /tmp/pim_vps_paywall_*.json /tmp/pim_v1_4_handoff/ 2>/dev/null || true
cp /tmp/pim_vps_x_*_dry_run.json /tmp/pim_v1_4_handoff/ 2>/dev/null || true
cp ~/.pim/data/eval_history.jsonl /tmp/pim_v1_4_handoff/ 2>/dev/null || true

journalctl -u personal-info-monitor --since "14 days ago" --no-pager \
  > /tmp/pim_v1_4_handoff/pim_systemd_14d.log 2>/dev/null || true
cp ~/.pim/data/pim.log /tmp/pim_v1_4_handoff/ 2>/dev/null || true
cp ~/.pim/data/pim.log.1 /tmp/pim_v1_4_handoff/ 2>/dev/null || true

sqlite3 ~/.pim/data/pim.db <<'SQL' > /tmp/pim_v1_4_handoff/pim_fetch_summary.csv
.headers on
.mode csv
SELECT s.name, s.type, COUNT(l.id) AS attempts,
       SUM(CASE WHEN l.outcome='success' THEN 1 ELSE 0 END) AS success,
       SUM(CASE WHEN l.outcome='failure' THEN 1 ELSE 0 END) AS failure,
       SUM(CASE WHEN l.outcome='empty' THEN 1 ELSE 0 END) AS empty,
       MAX(l.failure_code) AS sample_failure_code,
       SUM(l.saved_count) AS saved_count,
       SUM(l.fulltext_ok) AS fulltext_ok,
       SUM(l.fulltext_total) AS fulltext_total
FROM source_fetch_log l
JOIN sources s ON s.id = l.source_id
WHERE l.attempted_at >= datetime('now', '-14 days')
GROUP BY s.id
ORDER BY failure DESC, attempts DESC, s.name;
SQL

sqlite3 ~/.pim/data/pim.db <<'SQL' > /tmp/pim_v1_4_handoff/pim_session_health.csv
.headers on
.mode csv
SELECT name, type, url, session_health_status, session_health_reason,
       session_health_suggested_action, last_fetch_outcome_code,
       last_fetch_outcome_severity, last_fetch_outcome_updated_at
FROM sources
WHERE session_health_status IS NOT NULL
   OR last_fetch_outcome_code IS NOT NULL
ORDER BY type, name;
SQL

tar -czf /tmp/pim_v1_4_handoff.tar.gz -C /tmp pim_v1_4_handoff
```

如果 v1.3.1 数据库还没有 `source_fetch_log` 或 session health 结构化列，上面的 SQLite 查询可能失败。这不影响交接；请至少提供：

- `~/.pim/data/pim.db` 的备份路径或只读副本位置。
- `./pimctl sources list --json` 输出。
- 最近 14 天 `pim.log*` 或 systemd journal。
- 当前 `git rev-parse HEAD`、`git describe --tags --always`、`./pimctl --version`。
- 已有 `~/.pim/data/eval_history.jsonl`，如果存在。

## 5. v1.3.1 长期运行数据是否有帮助

有帮助，尤其是四类材料：

- 生产内容库：用于导出 500 条真实 eval candidates。
- 旧版日志：用于确认哪些源长期 warning/empty/error，避免把上游少发内容误判为 v1.4 回归。
- 来源配置：用于复现 X、付费墙、RSSHub、sitemap/discovery 真实路径。
- 旧 eval history：如果已有，可作为 v1.4 前的历史基线；如果没有，至少保留 v1.3.1 DB 备份，之后可在同一标注集上跑对照。

不要让 agent 回传明文密钥、cookie、Auth Bundle 或 `runtime-secrets.json`。需要验证登录态时，回传 dry-run JSON、session health 状态和日志摘要即可。
