# PIM 前端架构说明

Personal Information Monitor 的 Web/桌面前端，与后端 REST API 通信；桌面端通过 Tauri 2 打包为原生应用。

## 技术栈概述

| 类别 | 选型 |
|------|------|
| 运行时 | React 18 |
| 语言 | TypeScript |
| 构建 | Vite 5 |
| UI | Ant Design 5、@ant-design/icons |
| 样式 | Tailwind CSS 4（与 Ant Design 并存） |
| 路由 | React Router v6（`BrowserRouter` + `Routes`） |
| 服务端状态 | TanStack React Query v5（`QueryClientProvider`，默认 staleTime 5 分钟） |
| HTTP | Axios（统一实例 + 拦截器） |
| 桌面 | Tauri 2（`@tauri-apps/api`） |
| 测试 | Vitest（单元）、Playwright（E2E） |

依赖中还包含 **Zustand**，当前业务以 React Query 与组件内 `useState` 为主，可按需引入全局客户端状态。

## 目录结构

```
src/
├── App.tsx              # 路由与懒加载页面壳层
├── main.tsx             # React 根、QueryClient、Ant Design 中文、Router
├── config/
│   └── features.ts      # 编译期功能开关
├── pages/               # 路由级页面（Home、Digest、Reader、Settings 等）
├── components/          # 可复用 UI 与业务块
│   ├── layout/          # Header、Container、PageHeader
│   ├── ui/              # 通用展示组件（卡片、空态、搜索等）
│   ├── Dashboard/       # 首页仪表盘
│   ├── DigestView/      # 简报视图
│   ├── SourceList/      # 监控源管理
│   └── Settings/        # 设置各 Tab（分类、关键词、模型等）
├── services/            # API 封装、queryKeys、apiKey 存储
├── types/               # 与后端契约一致的 TypeScript 类型
├── utils/               # 工具函数（如日期时间）
└── styles/              # 全局 CSS（Tailwind 入口、主题变量）
```

`src-tauri/` 为 Tauri 原生工程（`tauri dev` / `tauri build` 使用）。

## 状态管理策略

- **服务端数据**：React Query（`useQuery` / `useMutation`），缓存键在 `services/queryKeys.ts` 等处按资源分层（例如 `sourceKeys`）。
- **客户端持久化**：API Key 等通过 `services/apiKeyStore.ts` 读写：浏览器端用 `localStorage` / `sessionStorage`；Tauri 运行时通过 `invoke('get_api_key' | 'set_api_key' | 'clear_api_key')` 走原生侧安全存储。
- **鉴权与请求**：`services/api.ts` 中 Axios 实例在请求拦截器里附加 `X-API-Key`，401 时协调单次恢复/重试；可与 `window.prompt` 及上述存储联动。
- **UI 状态**：页面与组件内部 state；无需全局 store 的场景不强制使用 Zustand。

## 组件分层

数据流大致为：**pages** 组合 **components**，通过 **services** 调用后端，类型由 **types** 约束。

1. **pages**：对应路由，负责拉取数据入口与布局拼装。
2. **components**：按功能域分子目录（Dashboard、Settings…），`layout/`、`ui/` 提供跨页面复用块。
3. **services**：按领域拆分模块（如 `sources.ts`、`contents.ts`、`digest.ts`），对外导出形如 `xxxApi` 的对象方法，内部统一使用默认导出的 `api` 实例。
4. **types**：`types/index.ts` 集中定义 Source、Content、Category、Keyword、Digest、分页结构等，与 REST 响应对齐。

## 路由结构

| 路径 | 说明 |
|------|------|
| `/` | 首页（仪表盘） |
| `/digest` | 每日简报 |
| `/reader/:id` | 阅读单条内容 |
| `/settings` | 设置（含原监控源相关能力） |
| `/sources` | 重定向至 `/settings` |
| `*` | 回退到 `/` |

页面使用 `React.lazy` + `Suspense` 按需加载。

## API 服务层设计

- **基地址**：`api.ts` 中 `getApiBaseURL()` — 开发环境可走 Vite 代理的 `/api`；设置 `VITE_API_URL` 可覆盖；**Tauri 打包**下无前端代理时默认直连 `http://127.0.0.1:8000/api`。
- **单一 Axios 实例**：超时、JSON、`X-API-Key` 与 401 恢复逻辑集中管理。
- **领域模块**：各 `services/*.ts` 只关心路径与参数，返回类型使用 `types` 与泛型分页 `PaginatedResponse<T>`。
- **缓存键**：`queryKeys.ts` 等用工厂函数生成层级化 key，便于 `invalidateQueries` 与列表参数区分。

## 功能开关（`config/features.ts`）

通过导出布尔常量控制编译期 UI/逻辑分支，例如：

- `PODCAST_SOURCES_ENABLED` — 播客相关能力
- `KEYWORD_MONITORING_ENABLED` — 关键词监控相关能力

修改后需重新构建前端生效。

## 构建与开发命令

| 命令 | 作用 |
|------|------|
| `npm install` | 安装依赖 |
| `npm run dev` | Vite 开发服务器（默认端口见 `vite.config`） |
| `npm run build` | `tsc` 类型检查 + 生产构建，输出 `dist/` |
| `npm run preview` | 本地预览生产构建 |
| `npm run test` | Vitest 单元测试 |
| `npm run lint` | ESLint |
| `npm run e2e` | Playwright E2E（需先 `e2e:install` 等） |

## Tauri 桌面端说明

- **配置**：`src-tauri/tauri.conf.json` — 开发时 `beforeDevCommand` 为 `npm run dev`，`devUrl` 指向本地前端；发布构建使用 `frontendDist: ../dist`。
- **运行时**：前端通过 `import.meta.env.TAURI_ENV_PLATFORM` 等与纯 Web 区分；API 基地址在桌面端默认指向本机后端端口。
- **API Key**：桌面端优先走 Tauri `invoke` 命令读写密钥，避免仅依赖浏览器存储。
- **常用命令**：`npm run tauri:dev` 联调桌面壳 + 前端；`npm run tauri:build` 打安装包（如 macOS dmg，见配置）。

---

更细粒度的页面功能说明可参考上文路由表；与后端 API 字段以 OpenAPI/后端文档为准。
