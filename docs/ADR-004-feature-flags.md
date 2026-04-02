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
