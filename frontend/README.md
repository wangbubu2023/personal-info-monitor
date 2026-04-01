# PIM 前端架构说明

Personal Information Monitor 的 Web/桌面前端，通过 REST API 与后端通信；桌面端由 Tauri 2 打包为原生应用。

## 技术栈概述

| 类别 | 选型 |
|------|------|
| 运行时 | React 18 |
| 语言 | TypeScript |
| 构建 | Vite 5 |
| UI | Ant Design 5、`@ant-design/icons` |
| 样式 | Tailwind CSS 4（与 Ant Design 并存） |
| 路由 | React Router v6（`BrowserRouter` + `Routes`） |
| 服务端状态 | TanStack React Query v5（`QueryClientProvider`，默认 `staleTime` 5 分钟、`retry` 1） |
| HTTP | Axios（单例 + 请求/响应拦截器） |
| 桌面 | Tauri 2（`@tauri-apps/api`） |
| 测试 | Vitest（单元）、Playwright（E2E） |
| 工具 | dayjs |

## 目录结构

```
src/
├── App.tsx              # 路由与懒加载页面
├── main.tsx             # 根节点、QueryClient、Ant Design 中文、`BrowserRouter`
├── config/
│   └── features.ts      # 编译期功能开关
├── pages/               # 路由级页面（Home、Digest、Reader、Settings 等）
├── components/          # 可复用 UI 与业务块（见下）
├── services/            # API 封装、queryKeys、apiKey 存储
├── types/               # 与后端契约一致的 TypeScript 类型
├── utils/               # 工具函数
└── styles/              # 全局 CSS（Tailwind 入口等）
```

**`components/` 主要子目录**：`layout/`（Header、Container、PageHeader）、`ui/`（ApiKeyModal、卡片、空态、搜索等通用块）、`Dashboard/`、`DigestView/`、`SourceList/`、`Settings/`（各设置 Tab）。

`src-tauri/` 为 Tauri 原生工程。

## 状态管理策略

- **服务端数据**：React Query（`useQuery` / `useMutation`）。缓存键在 `services/queryKeys.ts` 等处按资源分层（例如 `sourceKeys.all` / `list` / `list(params)`），便于 `invalidateQueries` 与列表参数区分。
- **客户端持久化**：API Key 等由 `services/apiKeyStore.ts` 处理——浏览器端可用 `localStorage` / `sessionStorage`；Tauri 运行时通过 `invoke('get_api_key' | 'set_api_key' | 'clear_api_key')` 走原生侧存储。
- **鉴权与请求**：`services/api.ts` 中 Axios 在请求拦截器里附加 `X-API-Key`（`ensureApiKey`）；401 时通过 `recoverApiKey` 协调单次恢复与重试，并与弹窗、`apiKeyStore` 联动。
- **UI 状态**：以页面与组件内 `useState` 为主；无全局客户端 store 依赖。

## 组件分层

数据流：**pages** → 组合 **components** → 调用 **services** → 类型由 **types** 约束。

1. **pages**：对应路由，负责数据入口与页面级布局。
2. **components**：按功能域分子目录；`layout/`、`ui/` 提供跨页面复用。
3. **services**：按领域拆分（如 `sources.ts`、`contents.ts`、`digest.ts`），对外导出 API 方法，内部统一使用 `api.ts` 默认导出的 Axios 实例。
4. **types**：`types/index.ts` 集中定义 Source、Content、Category、Keyword、Digest、`PaginatedResponse<T>`、系统设置与 AI 模型配置等，与 REST 响应对齐。

## 路由结构

| 路径 | 说明 |
|------|------|
| `/` | 首页（仪表盘） |
| `/digest` | 每日简报 |
| `/reader/:id` | 阅读单条内容 |
| `/settings` | 设置 |
| `/sources` | 重定向至 `/settings` |
| `*` | 回退到 `/` |

页面使用 `React.lazy` + `Suspense` 按需加载。

## API 服务层设计

- **基地址**：`getApiBaseURL()` / `normalizeApiBaseURL()`——开发可走 Vite 代理的 `/api`；环境变量 `VITE_API_URL` 可覆盖；**Tauri 打包**下默认 `http://127.0.0.1:8000/api`（无前端代理时直连本机后端）。
- **单一 Axios 实例**：超时 30s、JSON、`X-API-Key` 与 401 恢复逻辑集中管理。
- **领域模块**：各 `services/*.ts` 只关心路径与参数，返回类型使用 `types` 与 `PaginatedResponse<T>`。
- **缓存键**：`queryKeys.ts` 等用工厂函数生成层级化 key。

## 功能开关（`config/features.ts`）

通过导出布尔常量做编译期分支，修改后需重新构建生效：

| 常量 | 含义 |
|------|------|
| `PODCAST_SOURCES_ENABLED` | 播客相关能力 |
| `KEYWORD_MONITORING_ENABLED` | 关键词监控相关能力 |

## 构建与开发命令

| 命令 | 作用 |
|------|------|
| `npm install` | 安装依赖 |
| `npm run dev` | Vite 开发服务器 |
| `npm run build` | `tsc` + 生产构建，输出 `dist/` |
| `npm run preview` | 预览生产构建 |
| `npm run test` | Vitest 单元测试 |
| `npm run lint` | ESLint |
| `npm run e2e` | Playwright E2E（浏览器可先 `npm run e2e:install`） |
| `npm run tauri:dev` / `npm run tauri:build` | Tauri 开发 / 打包 |

## Tauri 桌面端说明

- **配置**：`src-tauri/tauri.conf.json`——开发时 `beforeDevCommand` 通常为前端 `npm run dev`，发布构建使用 `frontendDist: ../dist`。
- **运行时**：通过 `import.meta.env.TAURI_ENV_PLATFORM` 等与纯 Web 区分；API 基地址在桌面端默认指向本机后端。
- **API Key**：桌面端优先 Tauri `invoke` 读写，避免仅依赖浏览器存储。
- 详细行为以 `src-tauri` 与根目录 README 为准；与后端字段以 OpenAPI/后端文档为准。
