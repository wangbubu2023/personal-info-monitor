# 模块九：前端工程质量 审计报告

## 总评

**前端是这次审计里质量最高的部分**：
- TypeScript 严格模式 + noUnusedLocals/noUnusedParameters/noFallthroughCasesInSwitch（`tsconfig.json`），编译期就堵了不少坑；
- Vite 构建对生产环境**禁用 source map**、生产 minify、手工 manualChunks 拆 react-vendor / query-vendor / antd-* / 其它 vendor，包大小可控；
- `apiKeyStore.ts` 用 Strategy 模式（TauriKeyStorage / WebKeyStorage）封装两种运行时，**默认存到 sessionStorage**，仅在用户显式 `remember: true` 时落到 localStorage——这是教科书级的"减小 XSS 受害面"实现；
- bootstrap_token 通过后端注入的 `<meta name="pim-bootstrap-token">` 读取后立刻从 DOM 移除，**不留残影**给其它脚本；
- `useReader` 用 `AbortController.abort()` 在 cleanup 里取消 streaming，没有泄漏；
- React Query 全局 staleTime=5 分钟，对内容浏览类应用是合理的；
- `pages/*.tsx` 都是 8 行的薄包装，业务全在 `components/<Domain>/`，组件粒度健康；
- 仍有 frontend unit tests（KeywordsTab.test.tsx、Settings.test.tsx、keywordInputUtils.test.ts）。

主要可改进项：（1）19 处 `any` 使用分布未量化；（2）KeywordsTab.tsx 仍有 431 行，是接下来需要继续拆分的目标；（3）`useReader` 是 119 行，承担数据获取 + 流翻译 + 状态机，可以拆 hook；（4）依赖版本都是 0.x/1.x/5.x 主版本中较新的，但 antd 5.13.2 距 antd 5 最新有几个 minor 落后；（5）frontend 的 features.ts 与后端 features.py 仍是 ADR-004 提到的双份。

## 严重问题（❌）

无。

## 轻微问题（⚠️）

- **L1** `KeywordsTab.tsx` 仍有 431 行，是 components 中最大的单文件——继续拆为子组件可改善（虽然 ARCHITECTURE.md §5 已说"原 KeywordsTab.tsx 已拆"，剩余部分仍偏大）。
- **L2** 19 处 `any` 使用（`grep ': any\|<any>\| as any'`）——非零，但相对可控。建议逐个迁移到精确类型或 `unknown`。
- **L3** `useReader.ts` 119 行同时承担 reader 数据加载、stream 翻译、UI 状态机，可拆为 `useReaderData` + `useReaderTranslation` 两个 hook。
- **L4** Frontend 仍维护一份 `frontend/src/features.ts`（ADR-004 已说明），CI 比对脚本仅校验 flag 名，没校验默认值——参见 ADR-004 与模块一 L3。
- **L5** `frontend/package.json` 中 `antd ^5.13.2` 对应 2024 年 1 月版本；当前 antd 5 已经发到 5.20+，落后 7 个 minor，错失了若干虚拟列表、表单 perf 改进。
- **L6** vite.config 的 manualChunks 把 antd 主包不显式分组（returns undefined → 走 default），实际 antd 会进 vendor.js 的 default chunk；可显式 `return 'antd-core'` 让 chunk 命名更稳定。
- **L7** axios 全局 timeout=30s（`api.ts:40`），对一般 CRUD OK，但 reader 流接口走 streamReaderTranslation 的 fetch（不通过这个 axios 实例），需要确认那边的超时是否合理（基于模块四，每段 22s；总流可达数分钟）。

## 良好实践（✅）

- **G1** `apiKeyStore.ts` 默认 sessionStorage（`apiKeyStore.ts:179-191`），用户必须显式 `remember: true` 才落 localStorage——大幅缩小 XSS 受害窗口（关闭标签即失效）。
- **G2** Bootstrap token 路径优先从 `<meta name="pim-bootstrap-token">` 读取，**读完后立刻 `parentElement?.removeChild(meta)`**（`apiKeyStore.ts:113-119`），不让其它脚本截获。
- **G3** Bootstrap token 的 fallback 从 `?bootstrap_token=` query 参数读取，**读完用 `replaceState` 把参数从 URL 移除**（`apiKeyStore.ts:131-138`），不进浏览器历史/分析平台。
- **G4** 一次性 legacy migration：发现旧版 localStorage 存了 key 但没有 remember flag → 自动迁到 sessionStorage 并删 localStorage（`apiKeyStore.ts:166-174`），用户无感升级到更安全姿态。
- **G5** TypeScript `strict: true` + `noUnusedLocals: true` + `noUnusedParameters: true` + `noFallthroughCasesInSwitch: true`（`tsconfig.json:14-17`）——编译器层面堵了大量错误。
- **G6** Vite 生产 build：`sourcemap: !!process.env.TAURI_ENV_DEBUG`（`vite.config.ts:42`）——**生产环境 source map 关闭**，不泄漏源码。
- **G7** Vite manualChunks 拆 react-vendor / query-vendor / 各 antd-* 子包——首屏不必须全部 vendor JS（`vite.config.ts:46-72`）。
- **G8** React Query 全局 staleTime 5 分钟（`src/main.tsx:13`），对资讯类应用合理：用户切到另一个页面再回来不会立即 refetch。
- **G9** `pages/SettingsPage.tsx` 8 行（`pages/SettingsPage.tsx:1-7`），把渲染委托给 `components/Settings/Settings.tsx`——避免 GOD page。
- **G10** `useReader` cleanup 用 `AbortController.abort()`（`useReader.ts:86`），跳页或 useEffect rerun 时正确取消进行中的 streaming fetch。
- **G11** 前端有单元测试：`Settings.test.tsx`、`KeywordsTab.test.tsx`、`keywordInputUtils.test.ts`（`components/Settings/`），不只是组件搭出来就完。

## 详细审计清单

### 1. apiKeyStore.ts：API Key 存储 / XSS 受害面

- **结论：** ✅
- **代码位置：** `frontend/src/services/apiKeyStore.ts:1-237`
- **分析：**
  - **Tauri 模式**：通过 Rust `invoke('get_api_key' | 'set_api_key' | ...)`，存储在 0600 文件 `runtime-secrets.json`（与 ADR-003 一致）。
  - **Web 模式**：默认 sessionStorage（关闭 tab 即失效）；用户显式 `writeApiKey(value, { remember: true })` 才会写 localStorage。
  - sessionStorage / localStorage 都可被同源 JS 访问 → 任何 XSS 都能读出。但 sessionStorage 的"窗口期"小：必须 attacker 在用户当前 tab 还活着时执行 JS。
  - bootstrap_token 流程：(a) loopback Web 客户端从后端注入的 `<meta>` 读出 → 移除 meta tag → 调 `/local-token` 换 API Key → 存进 sessionStorage；(b) 一次性 URL `?bootstrap_token=...` 也支持，读后清掉。
  - 旧版用户的"无感升级"路径（L166-174）：legacyPersisted（localStorage 中有 key，但没 remember flag）→ 移到 sessionStorage、删 localStorage。
- **建议：** 无；这是 Web app 安全凭证存储能做到的合理上限。

### 2. api.ts：网络错误 / API 错误 / 错误边界

- **结论：** ⚠️
- **代码位置：** `frontend/src/services/api.ts`（仅前 100 行已审）
- **分析：**
  - axios 实例：baseURL 由运行时决定（VITE_API_URL > Tauri 直连 127.0.0.1 > 同源 /api proxy）。
  - timeout 30s。
  - 后续未读：interceptor 中如何区分 401（提示用户输 API Key）vs 5xx（toast 错误）vs 网络错误。从 prompt 调用名（`promptApiKey`、`__PIM_API_KEY_RECOVERY_PROMISE__`）看是有 401 自动恢复的。
  - **未在本次审计验证：** 全局错误边界（React ErrorBoundary）是否包住整个 App。
- **建议：**
  - 如果 App.tsx 没有 ErrorBoundary，加一个最外层的，把渲染异常 fallback 成"程序崩溃，请刷新"页面而不是白屏。

### 3. React Query 配置

- **结论：** ✅
- **代码位置：** `frontend/src/main.tsx:10-17`
- **分析：**
  - `staleTime: 1000 * 60 * 5`（5 分钟）→ 5 分钟内重复 useQuery 不会 refetch，节流明显。
  - 没有显式设 `gcTime`（v5 取代 cacheTime）→ 默认 5 分钟，与 staleTime 相同。这意味着用户切走 5 分钟内回来，缓存还在；超过 5 分钟则 cache 被 GC。这是合理默认。
  - `refetchOnWindowFocus`（默认 true）+ staleTime 5 min：用户切回 tab 时如果 stale 才会触发 refetch，否则不浪费请求。
- **建议：** 无；如果未来有"高频写"场景（例如订单），可以为该 queryKey 显式设短 staleTime。

### 4. 组件粒度：SettingsPage / GOD component

- **结论：** ✅（页面层）+ ⚠️（KeywordsTab 仍偏大）
- **代码位置：** `frontend/src/pages/SettingsPage.tsx`（8 行）、`frontend/src/components/Settings/Settings.tsx`（212 行）、`KeywordsTab.tsx`（431 行）
- **分析：**
  - Page 层是空壳：`SettingsPage` 8 行，仅 `<Settings />`。组件实现集中在 `components/Settings/`：
    - Settings.tsx 212 行：编排器（tabs 切换）；
    - KeywordsTab.tsx 431 行：单一 tab 仍偏厚；
    - AIModelTab.tsx、ModelProvidersTab.tsx、CredentialsTab.tsx：分 tab 独立；
    - keywords/ 子目录：进一步拆分关键词相关子组件（与 ARCHITECTURE.md §5 一致）。
- **建议：**
  - KeywordsTab.tsx 继续按"展示 / 筛选 / 编辑 / 批量操作"拆为 4 个子组件，目标每个 < 200 行。

### 5. Tauri 集成：CSP / CORS 差异

- **结论：** ✅
- **代码位置：** `frontend/src/services/api.ts:23-31`、`backend/app/main.py:185-192`、`backend/app/config.py:17-27`
- **分析：**
  - Tauri 打包后无 Vite proxy → axios baseURL 改为 `http://127.0.0.1:8000/api`（api.ts:28-30）。
  - 后端 CORS allow_origin_regex 允许 `tauri://localhost`（main.py:188）；config 默认列表也含 `http(s)://tauri.localhost` 兼容不同 WebView 平台（config.py:24-25）。
  - SPA index.html 的 CSP（main.py:42-57）`connect-src 'self' http://127.0.0.1:8000 http://localhost:8000` 在 Tauri WebView 里需要被 Tauri 自身的 CSP 覆盖（Tauri runtime 注入 capability-based CSP）；这部分依赖 Tauri 配置（src-tauri/tauri.conf.json）但本次未审。
- **建议：** 在 `src-tauri/tauri.conf.json` 中显式声明 connect-src 包含 backend 端口（避免 WebView 默认 CSP 阻止 `connect-src`）。

### 6. SSE / Stream useReader：内存泄漏

- **结论：** ✅
- **代码位置：** `frontend/src/hooks/useReader.ts:60-90`
- **分析：**
  - 使用 `AbortController + fetch`（不是 EventSource）发 NDJSON 请求。
  - useEffect 返回 `() => controller.abort()` cleanup，确保跳页或 deps 变化时立刻取消。
  - `.catch(() => { if (controller.signal.aborted) return; ... })` 区分"用户取消"与"真错误"——不会在已 unmount 的组件上 setState。
  - 没有看到明显的 EventSource 持有/未关。
- **建议：** 无。

### 7. TypeScript 严格度 / any 用量

- **结论：** ⚠️
- **代码位置：** `frontend/tsconfig.json`、`frontend/src/`（grep 19 处 any）
- **分析：**
  - tsconfig.json `strict: true` + `noUnusedLocals / noUnusedParameters / noFallthroughCasesInSwitch`：编译期严格。
  - 19 处 `any`：
    - 数量适中（中型项目通常 50-100+）；
    - 没看到 `.d.ts` 黑洞；
    - 根据 api.ts:74-89 的写法（`as { get?, X-API-Key? }`），项目偏好 `unknown` + 类型断言，比直接 any 好。
  - 后端 Pydantic schemas 与前端 TS interface 的对齐——没有自动生成机制（如 openapi-typescript），需要手工维护。漂移风险中等。
- **建议：**
  - 引入 `openapi-typescript` 或 `zodios` 从 FastAPI OpenAPI 生成 TS 类型，消除前后端类型漂移。
  - 19 处 any 逐一审视：能改 unknown 的改 unknown，需要 generic 的换 generic。

### 8. 构建产物：source map / bundle size

- **结论：** ✅
- **代码位置：** `frontend/vite.config.ts:38-72`
- **分析：**
  - **source map 仅在 `TAURI_ENV_DEBUG` 时生成**（L42 `sourcemap: !!process.env.TAURI_ENV_DEBUG`），生产构建无 source map → **不会泄漏到生产**。
  - minify: esbuild（除非 TAURI_ENV_DEBUG），是最快也是最佳压缩比之一。
  - manualChunks 拆分：
    - react-vendor（react/react-dom/router）
    - query-vendor（@tanstack/react-query）
    - antd-* 子包（@ant-design/icons、rc-*）单独命名
    - 其它 node_modules 走 `vendor-<pkg>`
  - antd 主包**没有显式 chunk 名**（L62 `if (pkg === 'antd') return;` 即 returns undefined → 走默认 chunk），意味着 antd 5 全量进了 default vendor chunk。这是**目前最大的 bundle 单点**。
- **建议：**
  - 给 antd 显式 `return 'antd-core'`，让 chunk 命名稳定可缓存；
  - 考虑 antd 的 tree-shake：用 import path `import Button from 'antd/es/button'` 取代 barrel import（如果还没做）。

## 涉及文件

- `frontend/tsconfig.json`
- `frontend/vite.config.ts`
- `frontend/package.json`
- `frontend/src/services/apiKeyStore.ts`
- `frontend/src/services/api.ts`（前 100 行）
- `frontend/src/main.tsx`（grep 验证 React Query 配置）
- `frontend/src/pages/SettingsPage.tsx` + `frontend/src/components/Settings/Settings.tsx`
- `frontend/src/components/Settings/KeywordsTab.tsx`
- `frontend/src/hooks/useReader.ts`、`useDashboard.ts`
- `frontend/src/components/`（结构概览）

## 立即可落地的改进

1. 给 `vite.config.ts` 的 antd 主包显式命名 chunk（`return 'antd-core'`）。
2. 引入 `openapi-typescript`：FastAPI → openapi.json → 生成 `frontend/src/types/api.ts`，前后端类型同源。
3. `KeywordsTab.tsx` 继续按职责拆 4 子组件。
4. App.tsx 加 ErrorBoundary 兜底渲染异常。
5. `package.json` 升级 antd 到 5.20+ minor（无破坏性变更）。
