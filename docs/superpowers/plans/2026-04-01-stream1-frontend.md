# Stream 1: Frontend SourceManager 重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 1299 行的 SourceManager.tsx 按逻辑下沉+视图拆分策略重构为 4 个视图组件和 3 个 hooks，消除与 APIKeysTab 的重复辅助函数。

**Architecture:** 从 SourceManager 提取共享工具函数到 sourceAuth.ts；三个 hooks 各自封装一类业务逻辑；SourceListContainer 组合 hooks 并向 Modal 组件传递回调；SourceManager.tsx 变为薄壳保持对外接口不变。

**Tech Stack:** React 18, TypeScript, Ant Design, TanStack Query, Vitest

---

### Task 1: 提取 sourceAuth.ts + 更新 APIKeysTab

**Files:**
- Create: `frontend/src/utils/sourceAuth.ts`
- Create: `frontend/src/utils/sourceAuth.test.ts`
- Modify: `frontend/src/components/Settings/APIKeysTab.tsx`

**背景：** `SourceManager.tsx` 第 43–67 行定义了 5 个纯工具函数；`APIKeysTab.tsx` 第 28–41 行重复定义了其中 2 个（`normalizeHost`、`isXCookieProfile`）。将这 5 个函数提取到共享模块，并让 APIKeysTab 改为从新模块导入。

- [ ] **Step 1: 先写测试文件**

创建 `frontend/src/utils/sourceAuth.test.ts`：

```ts
import { describe, expect, it } from 'vitest'
import {
  normalizeHost,
  resolveSiteUrlForAuth,
  isXCookieProfile,
  getAuthConfigDisplayName,
  getDefaultSharedXAuthConfigId,
} from './sourceAuth'
import type { AuthConfig } from '../services/configs'

// --- normalizeHost ---
describe('normalizeHost', () => {
  it('returns empty string for undefined', () => {
    expect(normalizeHost(undefined)).toBe('')
  })

  it('strips www prefix', () => {
    expect(normalizeHost('https://www.example.com')).toBe('example.com')
  })

  it('lowercases the hostname', () => {
    expect(normalizeHost('https://EXAMPLE.COM')).toBe('example.com')
  })

  it('prepends https:// when scheme is absent', () => {
    expect(normalizeHost('example.com')).toBe('example.com')
  })

  it('returns empty string for invalid URL', () => {
    expect(normalizeHost('not a url !!!')).toBe('')
  })
})

// --- resolveSiteUrlForAuth ---
describe('resolveSiteUrlForAuth', () => {
  it('converts host to https origin', () => {
    expect(resolveSiteUrlForAuth('www.example.com')).toBe('https://example.com')
  })

  it('returns value as-is when host cannot be resolved', () => {
    expect(resolveSiteUrlForAuth('not a url !!!')).toBe('not a url !!!')
  })

  it('returns empty string for undefined', () => {
    expect(resolveSiteUrlForAuth(undefined)).toBe('')
  })
})

// --- isXCookieProfile ---
const makeAuth = (overrides: Partial<AuthConfig>): AuthConfig => ({
  id: 'test-id',
  site_url: 'https://x.com',
  auth_type: 'cookie',
  is_shared: false,
  status: 'active',
  login_selectors: {},
  has_credentials: true,
  bound_source_count: 0,
  created_at: '',
  updated_at: '',
  ...overrides,
})

describe('isXCookieProfile', () => {
  it('returns true for x.com cookie config', () => {
    expect(isXCookieProfile(makeAuth({ site_url: 'https://x.com', auth_type: 'cookie' }))).toBe(true)
  })

  it('returns true for twitter.com cookie config', () => {
    expect(isXCookieProfile(makeAuth({ site_url: 'https://twitter.com', auth_type: 'cookie' }))).toBe(true)
  })

  it('returns false for non-cookie auth_type', () => {
    expect(isXCookieProfile(makeAuth({ site_url: 'https://x.com', auth_type: 'password' }))).toBe(false)
  })

  it('returns false for unrelated site', () => {
    expect(isXCookieProfile(makeAuth({ site_url: 'https://example.com', auth_type: 'cookie' }))).toBe(false)
  })
})

// --- getAuthConfigDisplayName ---
describe('getAuthConfigDisplayName', () => {
  it('returns name when set', () => {
    expect(getAuthConfigDisplayName(makeAuth({ name: 'My Profile' }))).toBe('My Profile')
  })

  it('generates fallback from site_url and id prefix', () => {
    const cfg = makeAuth({ name: undefined, site_url: 'https://x.com', id: 'abcdefgh-1234' })
    expect(getAuthConfigDisplayName(cfg)).toMatch(/x\.com/)
    expect(getAuthConfigDisplayName(cfg)).toMatch(/abcdefgh/)
  })

  it('uses 凭证 as host fallback when site_url is empty', () => {
    const cfg = makeAuth({ name: undefined, site_url: '', id: 'abcdefgh-1234' })
    expect(getAuthConfigDisplayName(cfg)).toContain('凭证')
  })
})

// --- getDefaultSharedXAuthConfigId ---
describe('getDefaultSharedXAuthConfigId', () => {
  it('returns undefined for empty array', () => {
    expect(getDefaultSharedXAuthConfigId([])).toBeUndefined()
  })

  it('returns the id of the first config', () => {
    const cfg = makeAuth({ id: 'first-id' })
    expect(getDefaultSharedXAuthConfigId([cfg])).toBe('first-id')
  })
})
```

- [ ] **Step 2: 验证测试失败（文件尚不存在）**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/frontend && npm test -- --run src/utils/sourceAuth.test.ts 2>&1 | tail -20
```

Expected: 测试因找不到 `./sourceAuth` 模块而报错

- [ ] **Step 3: 创建 sourceAuth.ts 实现**

创建 `frontend/src/utils/sourceAuth.ts`：

```ts
import type { AuthConfig } from '../services/configs'

/**
 * 将任意 URL / 主机名规范化为小写裸主机名（去除 www. 前缀）。
 * 无效输入返回空字符串。
 */
export const normalizeHost = (value?: string): string => {
  try {
    if (!value) return ''
    const raw = value.includes('://') ? value : `https://${value}`
    return (new URL(raw).hostname || '').toLowerCase().replace(/^www\./, '')
  } catch {
    return ''
  }
}

/**
 * 将 URL / 主机名转换为认证用的 site_url（形如 https://example.com）。
 */
export const resolveSiteUrlForAuth = (value?: string): string => {
  const host = normalizeHost(value)
  return host ? `https://${host}` : (value || '')
}

/**
 * 判断 AuthConfig 是否为 X (Twitter) 的 Cookie 登录态。
 */
export const isXCookieProfile = (config: AuthConfig): boolean => {
  const host = normalizeHost(config.site_url)
  return config.auth_type === 'cookie' && (host === 'x.com' || host === 'twitter.com')
}

/**
 * 返回 AuthConfig 的可读显示名称。
 * 优先使用 config.name；无名称时回退为 "host · id前8位"。
 */
export const getAuthConfigDisplayName = (config: AuthConfig): string =>
  config.name?.trim() || `${normalizeHost(config.site_url) || '凭证'} · ${config.id.slice(0, 8)}`

/**
 * 从共享 X 登录态列表中返回默认选项的 id（取第一条）。
 */
export const getDefaultSharedXAuthConfigId = (configs: AuthConfig[] = []): string | undefined =>
  configs[0]?.id
```

- [ ] **Step 4: 验证测试通过**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/frontend && npm test -- --run src/utils/sourceAuth.test.ts 2>&1 | tail -20
```

Expected: 所有测试通过，无失败

- [ ] **Step 5: 更新 APIKeysTab.tsx，改为从 sourceAuth.ts 导入**

修改 `frontend/src/components/Settings/APIKeysTab.tsx`：

删除第 28–41 行的本地定义：
```ts
const normalizeHost = (value?: string): string => {
  try {
    if (!value) return ''
    const raw = value.includes('://') ? value : `https://${value}`
    return (new URL(raw).hostname || '').toLowerCase().replace(/^www\./, '')
  } catch {
    return ''
  }
}

const isXCookieProfile = (config: AuthConfig): boolean => {
  const host = normalizeHost(config.site_url)
  return config.auth_type === 'cookie' && (host === 'x.com' || host === 'twitter.com')
}
```

在 import 区（紧接现有 import 行之后）添加：
```ts
import { normalizeHost, isXCookieProfile } from '../../utils/sourceAuth'
```

- [ ] **Step 6: 运行 lint + 全量测试确认无回归**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/frontend && npm run lint && npm test -- --run 2>&1 | tail -30
```

Expected: lint 无报错，全量测试通过

- [ ] **Step 7: Commit**

```bash
cd /Users/shuhuaiwang/personal-info-monitor && git add frontend/src/utils/sourceAuth.ts frontend/src/utils/sourceAuth.test.ts frontend/src/components/Settings/APIKeysTab.tsx && git commit -m "refactor: extract shared auth utils to sourceAuth.ts, remove duplication in APIKeysTab"
```

---

### Task 2: 实现 useSourceList hook

**Files:**
- Create: `frontend/src/components/SourceList/hooks/useSourceList.ts`
- Create: `frontend/src/components/SourceList/hooks/useSourceList.test.ts`

**背景：** 将 SourceManager.tsx 中分页、搜索（debounce 300ms）、tab 计数查询、行选择、列表 query、quota query 的所有 state 和 queries 提取到独立 hook。

- [ ] **Step 1: 先写测试文件**

创建 `frontend/src/components/SourceList/hooks/useSourceList.test.ts`：

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

// Mock service layer
vi.mock('../../../services/sources', () => ({
  listSources: vi.fn(),
  sourcesApi: { list: vi.fn() },
}))
vi.mock('../../../services/queryKeys', () => ({
  sourceKeys: { all: ['sources'], lists: () => ['sources', 'list'], list: (p: unknown) => ['sources', 'list', p] },
}))

import { listSources } from '../../../services/sources'
import { useSourceList } from './useSourceList'

const mockListSources = vi.mocked(listSources)

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return React.createElement(QueryClientProvider, { client: qc }, children)
}

const emptyPage = { items: [], total: 0, page: 1, page_size: 20, total_pages: 0 }

beforeEach(() => {
  vi.clearAllMocks()
  mockListSources.mockResolvedValue(emptyPage)
})

describe('useSourceList', () => {
  it('initialises with page=1, pageSize=20, activeTypeFilter=all', () => {
    const { result } = renderHook(() => useSourceList(), { wrapper })
    expect(result.current.page).toBe(1)
    expect(result.current.pageSize).toBe(20)
    expect(result.current.activeTypeFilter).toBe('all')
  })

  it('resets page to 1 when activeTypeFilter changes', async () => {
    const { result } = renderHook(() => useSourceList(), { wrapper })
    act(() => { result.current.setPage(3) })
    expect(result.current.page).toBe(3)
    act(() => { result.current.setActiveTypeFilter('rss') })
    await waitFor(() => expect(result.current.page).toBe(1))
  })

  it('resets selectedRowKeys when page changes', async () => {
    const { result } = renderHook(() => useSourceList(), { wrapper })
    act(() => { result.current.setSelectedRowKeys(['id1', 'id2']) })
    expect(result.current.selectedRowKeys).toHaveLength(2)
    act(() => { result.current.setPage(2) })
    await waitFor(() => expect(result.current.selectedRowKeys).toHaveLength(0))
  })

  it('debounces searchInput by 300ms', async () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useSourceList(), { wrapper })
    act(() => { result.current.setSearchInput('hello') })
    expect(result.current.debouncedSearch).toBe('')
    act(() => { vi.advanceTimersByTime(300) })
    await waitFor(() => expect(result.current.debouncedSearch).toBe('hello'))
    vi.useRealTimers()
  })
})
```

- [ ] **Step 2: 验证测试失败**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/frontend && npm test -- --run src/components/SourceList/hooks/useSourceList.test.ts 2>&1 | tail -20
```

Expected: 测试因找不到 `./useSourceList` 而报错

- [ ] **Step 3: 创建 hooks 目录并实现 useSourceList.ts**

```bash
mkdir -p /Users/shuhuaiwang/personal-info-monitor/frontend/src/components/SourceList/hooks
```

创建 `frontend/src/components/SourceList/hooks/useSourceList.ts`：

```ts
import { useState, useEffect } from 'react'
import type React from 'react'
import { useQuery, useQueries } from '@tanstack/react-query'
import { listSources } from '../../../services/sources'
import { categoriesApi } from '../../../services/categories'
import { configsApi } from '../../../services/configs'
import { sourceKeys } from '../../../services/queryKeys'

export const typeFilters = [
  { key: 'all', label: '全部' },
  { key: 'website', label: '网站/博客' },
  { key: 'rss', label: 'RSS' },
  { key: 'x', label: 'X (Twitter)' },
  { key: 'youtube', label: 'YouTube' },
]

export function useSourceList() {
  const [activeTypeFilter, setActiveTypeFilter] = useState('all')
  const [searchInput, setSearchInput] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])

  // Debounce search input
  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedSearch(searchInput.trim()), 300)
    return () => window.clearTimeout(t)
  }, [searchInput])

  // Reset page on filter/search change
  useEffect(() => {
    setPage(1)
  }, [debouncedSearch, activeTypeFilter])

  // Reset row selection when page/filter/search changes
  useEffect(() => {
    setSelectedRowKeys([])
  }, [page, pageSize, debouncedSearch, activeTypeFilter])

  const listParams = {
    page,
    page_size: pageSize,
    search: debouncedSearch || undefined,
    type: activeTypeFilter === 'all' ? undefined : activeTypeFilter,
    scope: 'library' as const,
  }

  const {
    data: listData,
    isLoading,
    isError,
    error,
    isFetching,
    refetch: refetchSources,
  } = useQuery({
    queryKey: sourceKeys.list(listParams),
    queryFn: () => listSources(listParams),
  })

  const { data: quotaData } = useQuery({
    queryKey: [...sourceKeys.all, 'quota-total'],
    queryFn: () => listSources({ page: 1, page_size: 1 }),
    staleTime: 30_000,
  })

  const { data: allTabCountData } = useQuery({
    queryKey: [...sourceKeys.all, 'tab-total', 'all', debouncedSearch],
    queryFn: () =>
      listSources({ page: 1, page_size: 1, search: debouncedSearch || undefined }),
    staleTime: 30_000,
  })

  const typeTabCountQueries = useQueries({
    queries: typeFilters
      .filter((f) => f.key !== 'all')
      .map((f) => ({
        queryKey: [...sourceKeys.all, 'tab-total', f.key, debouncedSearch],
        queryFn: () =>
          listSources({ page: 1, page_size: 1, type: f.key, search: debouncedSearch || undefined }),
        staleTime: 30_000,
      })),
  })

  const { data: categories } = useQuery({
    queryKey: ['categories', 'flat'],
    queryFn: () => categoriesApi.list(true),
  })

  const { data: authConfigs } = useQuery({
    queryKey: ['auth-configs'],
    queryFn: configsApi.listAuthConfigs,
  })

  const { data: systemSettings } = useQuery({
    queryKey: ['system-settings'],
    queryFn: configsApi.getSettings,
  })

  const sources = listData?.items ?? []
  const sourceCount = quotaData?.total ?? 0
  const maxSources = Number(systemSettings?.limits?.max_sources || 200)
  const remainingSources = Math.max(0, maxSources - sourceCount)
  const sourceLimitReached = sourceCount >= maxSources
  const sourceLoadError =
    (error as { response?: { data?: { detail?: string } }; message?: string } | null)?.response?.data?.detail ||
    (error as { message?: string } | null)?.message ||
    '信源加载失败，请稍后重试。'

  const getTypeCount = (typeKey: string): number => {
    if (typeKey === 'all') return allTabCountData?.total ?? 0
    const idx = typeFilters.filter((f) => f.key !== 'all').findIndex((f) => f.key === typeKey)
    if (idx < 0) return 0
    return typeTabCountQueries[idx]?.data?.total ?? 0
  }

  return {
    // State
    activeTypeFilter,
    setActiveTypeFilter,
    searchInput,
    setSearchInput,
    debouncedSearch,
    page,
    setPage,
    pageSize,
    setPageSize,
    selectedRowKeys,
    setSelectedRowKeys,
    // Derived / query data
    sources,
    listData,
    isLoading,
    isError,
    error,
    isFetching,
    refetchSources,
    categories,
    authConfigs,
    systemSettings,
    sourceCount,
    maxSources,
    remainingSources,
    sourceLimitReached,
    sourceLoadError,
    getTypeCount,
  }
}
```

- [ ] **Step 4: 验证测试通过**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/frontend && npm test -- --run src/components/SourceList/hooks/useSourceList.test.ts 2>&1 | tail -20
```

Expected: 所有测试通过

- [ ] **Step 5: 运行 lint**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/frontend && npm run lint 2>&1 | tail -20
```

Expected: 无报错

- [ ] **Step 6: Commit**

```bash
cd /Users/shuhuaiwang/personal-info-monitor && git add frontend/src/components/SourceList/hooks/useSourceList.ts frontend/src/components/SourceList/hooks/useSourceList.test.ts && git commit -m "feat: add useSourceList hook extracting list/filter/search/quota state from SourceManager"
```

---

### Task 3: 实现 useSourceEditor hook

**Files:**
- Create: `frontend/src/components/SourceList/hooks/useSourceEditor.ts`
- Create: `frontend/src/components/SourceList/hooks/useSourceEditor.test.ts`

**背景：** 将 SourceManager.tsx 中与 Modal 编辑/新增相关的状态和 mutations 提取到 hook：`editingSource`、`form`、`isModalOpen`、createMutation/updateMutation/deleteMutation/fetchMutation/probeMutation/probeAllMutation，以及 `handleSubmit`、`handleEdit`、`handleAdd`、`matchAuthConfigByHost`。

- [ ] **Step 1: 先写测试文件**

创建 `frontend/src/components/SourceList/hooks/useSourceEditor.test.ts`：

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('../../../services/sources', () => ({
  sourcesApi: {
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    triggerFetch: vi.fn(),
    probeSource: vi.fn(),
    probeAll: vi.fn(),
  },
}))
vi.mock('../../../services/configs', () => ({
  configsApi: { createAuthConfig: vi.fn(), updateAuthConfig: vi.fn(), listAuthConfigs: vi.fn() },
}))
vi.mock('../../../services/queryKeys', () => ({
  sourceKeys: { all: ['sources'], lists: () => ['sources', 'list'], list: (p: unknown) => ['sources', 'list', p] },
}))
vi.mock('../../../utils/sourceAuth', () => ({
  normalizeHost: vi.fn((v?: string) => {
    if (!v) return ''
    try { return new URL(v.includes('://') ? v : `https://${v}`).hostname.replace(/^www\./, '') } catch { return '' }
  }),
  resolveSiteUrlForAuth: vi.fn((v?: string) => v || ''),
  isXCookieProfile: vi.fn(() => false),
  getAuthConfigDisplayName: vi.fn(() => 'display'),
  getDefaultSharedXAuthConfigId: vi.fn(() => undefined),
}))

import { useSourceEditor } from './useSourceEditor'

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return React.createElement(QueryClientProvider, { client: qc }, children)
}

describe('useSourceEditor', () => {
  beforeEach(() => vi.clearAllMocks())

  it('initialises with isModalOpen=false and editingSource=null', () => {
    const { result } = renderHook(() => useSourceEditor({ authConfigs: [], sourceLimitReached: false, maxSources: 200, remainingSources: 200, sharedXAuthConfigs: [], defaultSharedXAuthConfigId: undefined }), { wrapper })
    expect(result.current.isModalOpen).toBe(false)
    expect(result.current.editingSource).toBeNull()
  })

  it('handleAdd opens modal and resets editingSource', () => {
    const { result } = renderHook(() => useSourceEditor({ authConfigs: [], sourceLimitReached: false, maxSources: 200, remainingSources: 200, sharedXAuthConfigs: [], defaultSharedXAuthConfigId: undefined }), { wrapper })
    act(() => { result.current.handleAdd() })
    expect(result.current.isModalOpen).toBe(true)
    expect(result.current.editingSource).toBeNull()
  })

  it('handleAdd does not open modal when sourceLimitReached=true', () => {
    const { result } = renderHook(() => useSourceEditor({ authConfigs: [], sourceLimitReached: true, maxSources: 200, remainingSources: 0, sharedXAuthConfigs: [], defaultSharedXAuthConfigId: undefined }), { wrapper })
    act(() => { result.current.handleAdd() })
    expect(result.current.isModalOpen).toBe(false)
  })

  it('matchAuthConfigByHost returns undefined for empty configs', () => {
    const { result } = renderHook(() => useSourceEditor({ authConfigs: [], sourceLimitReached: false, maxSources: 200, remainingSources: 200, sharedXAuthConfigs: [], defaultSharedXAuthConfigId: undefined }), { wrapper })
    expect(result.current.matchAuthConfigByHost('https://example.com', [])).toBeUndefined()
  })
})
```

- [ ] **Step 2: 验证测试失败**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/frontend && npm test -- --run src/components/SourceList/hooks/useSourceEditor.test.ts 2>&1 | tail -20
```

Expected: 测试因找不到 `./useSourceEditor` 而报错

- [ ] **Step 3: 实现 useSourceEditor.ts**

创建 `frontend/src/components/SourceList/hooks/useSourceEditor.ts`：

```ts
import { useState } from 'react'
import { Form, message } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { sourcesApi } from '../../../services/sources'
import { configsApi, type AuthConfig } from '../../../services/configs'
import { sourceKeys } from '../../../services/queryKeys'
import type { Source, SourceCreate, SourceType } from '../../../types'
import { parseUrlLines } from '../importUtils'
import {
  normalizeHost,
  resolveSiteUrlForAuth,
  isXCookieProfile,
  getAuthConfigDisplayName,
} from '../../../utils/sourceAuth'

export { getAuthConfigDisplayName }

interface SourceFormValues extends Omit<SourceCreate, 'extra_urls'> {
  extra_urls_text?: string
  paywall_enabled?: boolean
  x_cookie_enabled?: boolean
  x_auth_mode?: 'shared' | 'dedicated'
  x_shared_auth_config_id?: string
  x_auth_name?: string
  auth_type?: string
  login_url?: string
  username?: string
  password?: string
  cookies?: string
  x_auth_token?: string
  x_ct0?: string
}

interface UseSourceEditorOptions {
  authConfigs: AuthConfig[]
  sourceLimitReached: boolean
  maxSources: number
  remainingSources: number
  sharedXAuthConfigs: AuthConfig[]
  defaultSharedXAuthConfigId: string | undefined
}

export function useSourceEditor({
  authConfigs,
  sourceLimitReached,
  maxSources,
  sharedXAuthConfigs,
  defaultSharedXAuthConfigId,
}: UseSourceEditorOptions) {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingSource, setEditingSource] = useState<Source | null>(null)
  const [form] = Form.useForm<SourceFormValues>()
  const queryClient = useQueryClient()

  const invalidateSources = () => queryClient.invalidateQueries({ queryKey: sourceKeys.all })

  const createMutation = useMutation({
    mutationFn: sourcesApi.create,
    onSuccess: () => {
      invalidateSources()
      message.success('创建成功')
      setIsModalOpen(false)
      form.resetFields()
    },
    onError: (error: any) => {
      const detail = error?.response?.data?.detail
      message.error(detail ? `创建失败：${detail}` : '创建失败')
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<SourceCreate> }) =>
      sourcesApi.update(id, data),
    onSuccess: () => {
      invalidateSources()
      message.success('更新成功')
      setIsModalOpen(false)
      setEditingSource(null)
      form.resetFields()
    },
    onError: (error: any) => {
      const detail = error?.response?.data?.detail
      message.error(detail ? `更新失败：${detail}` : '更新失败')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: sourcesApi.delete,
    onSuccess: () => { invalidateSources(); message.success('删除成功') },
    onError: () => { message.error('删除失败') },
  })

  const fetchMutation = useMutation({
    mutationFn: sourcesApi.triggerFetch,
    onSuccess: () => { message.success('已触发抓取任务') },
    onError: () => { message.error('触发失败') },
  })

  const probeMutation = useMutation({
    mutationFn: sourcesApi.probeSource,
    onSuccess: () => { invalidateSources(); message.success('探测完成') },
    onError: () => { message.error('探测失败') },
  })

  const probeAllMutation = useMutation({
    mutationFn: sourcesApi.probeAll,
    onSuccess: (data) => { invalidateSources(); message.success(`已探测 ${data.total} 个源`) },
    onError: () => { message.error('批量探测失败') },
  })

  const matchAuthConfigByHost = (url: string, configs: AuthConfig[] = []): AuthConfig | undefined => {
    const sourceHost = normalizeHost(url)
    if (!sourceHost) return undefined
    return configs.find((cfg) => {
      const cfgHost = normalizeHost(cfg.site_url)
      return !!cfgHost && (
        sourceHost === cfgHost ||
        sourceHost.endsWith(`.${cfgHost}`) ||
        cfgHost.endsWith(`.${sourceHost}`)
      )
    })
  }

  const handleSubmit = async (values: SourceFormValues) => {
    const {
      extra_urls_text,
      paywall_enabled,
      x_cookie_enabled,
      x_auth_mode,
      x_shared_auth_config_id,
      x_auth_name,
      auth_type,
      login_url,
      username,
      password,
      cookies,
      x_auth_token,
      x_ct0,
      ...rest
    } = values

    const payload: SourceCreate = {
      ...rest,
      extra_urls: parseUrlLines(extra_urls_text),
    }

    if (!editingSource && sourceLimitReached) {
      message.warning(`监控源已达上限（${maxSources}），请先删除部分信源再添加。`)
      return
    }

    try {
      if (payload.type === 'website') {
        const enablePaywall = Boolean(paywall_enabled)
        if (enablePaywall) {
          const site_url = resolveSiteUrlForAuth(payload.url)
          let targetAuth =
            authConfigs?.find((cfg) => cfg.id === editingSource?.auth_config_id) ||
            matchAuthConfigByHost(payload.url, authConfigs || [])

          const authPayload = {
            site_url,
            auth_type: auth_type || 'password',
            login_url: login_url || undefined,
            username: username || undefined,
            password: password || undefined,
            cookies: cookies || undefined,
          }

          if (targetAuth) {
            await configsApi.updateAuthConfig(targetAuth.id, authPayload)
          } else {
            targetAuth = await configsApi.createAuthConfig(authPayload)
          }
          await queryClient.invalidateQueries({ queryKey: ['auth-configs'] })

          payload.auth_required = true
          payload.auth_config_id = targetAuth.id
        } else {
          payload.auth_required = false
          ;(payload as SourceCreate & { auth_config_id: string | null }).auth_config_id = null
        }
      } else if (payload.type === 'x') {
        const enableXCookie = Boolean(x_cookie_enabled)
        if (enableXCookie) {
          const selectedMode = x_auth_mode || (sharedXAuthConfigs.length > 0 ? 'shared' : 'dedicated')
          if (selectedMode === 'shared') {
            if (!x_shared_auth_config_id) {
              message.error('保存失败：请选择一个共享 X 登录态')
              return
            }
            payload.auth_required = true
            payload.auth_config_id = x_shared_auth_config_id
          } else {
            const existingLinkedAuth = authConfigs?.find((cfg) => cfg.id === editingSource?.auth_config_id)
            const canReuseExistingDedicated = Boolean(
              existingLinkedAuth && !existingLinkedAuth.is_shared && isXCookieProfile(existingLinkedAuth)
            )
            const authToken = (x_auth_token || '').trim()
            const ct0 = (x_ct0 || '').trim()
            const profileName = (x_auth_name || '').trim()
            const hasCookieUpdate = Boolean(authToken || ct0)

            if (hasCookieUpdate && (!authToken || !ct0)) {
              message.error('保存失败：请同时填写 auth_token 和 ct0')
              return
            }
            if (!hasCookieUpdate && !canReuseExistingDedicated) {
              message.error('保存失败：请填写专用 X 登录态的 auth_token 和 ct0')
              return
            }

            let savedAuth = existingLinkedAuth
            if (hasCookieUpdate) {
              const authPayload = {
                name: profileName || existingLinkedAuth?.name || `${payload.name} 专用 X 登录态`,
                site_url: 'https://x.com',
                auth_type: 'cookie',
                is_shared: false,
                cookies: { auth_token: authToken, ct0 },
              }
              savedAuth = canReuseExistingDedicated
                ? await configsApi.updateAuthConfig(existingLinkedAuth!.id, authPayload)
                : await configsApi.createAuthConfig(authPayload)
              await queryClient.invalidateQueries({ queryKey: ['auth-configs'] })
            }

            payload.auth_required = true
            payload.auth_config_id = savedAuth?.id
          }
        } else {
          payload.auth_required = false
          ;(payload as SourceCreate & { auth_config_id: string | null }).auth_config_id = null
        }
      }

      if (editingSource) {
        updateMutation.mutate({ id: editingSource.id, data: payload })
      } else {
        createMutation.mutate(payload)
      }
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(detail ? `保存失败：${detail}` : '保存失败：认证配置未更新')
    }
  }

  const handleEdit = (source: Source) => {
    const linkedAuth =
      authConfigs?.find((cfg) => cfg.id === source.auth_config_id) ||
      (source.type === 'website' ? matchAuthConfigByHost(source.url, authConfigs || []) : undefined)
    setEditingSource(source)
    const xMode: 'shared' | 'dedicated' | undefined =
      source.type === 'x'
        ? linkedAuth?.is_shared
          ? 'shared'
          : linkedAuth
            ? 'dedicated'
            : sharedXAuthConfigs.length > 0
              ? 'shared'
              : 'dedicated'
        : undefined
    form.setFieldsValue({
      ...source,
      extra_urls_text: (source.extra_urls || []).join('\n'),
      paywall_enabled: Boolean(source.auth_required || source.auth_config_id || linkedAuth),
      x_cookie_enabled: Boolean(source.type === 'x' && (source.auth_required || source.auth_config_id || linkedAuth)),
      x_auth_mode: xMode,
      x_shared_auth_config_id: xMode === 'shared' ? linkedAuth?.id : undefined,
      x_auth_name: !linkedAuth?.is_shared ? linkedAuth?.name || undefined : undefined,
      auth_type: linkedAuth?.auth_type || 'password',
      login_url: linkedAuth?.login_url || undefined,
      username: undefined,
      password: undefined,
      cookies: undefined,
      x_auth_token: undefined,
      x_ct0: undefined,
    })
    setIsModalOpen(true)
  }

  const handleAdd = () => {
    if (sourceLimitReached) {
      message.warning(`监控源已达上限（${maxSources}），请先删除部分信源再添加。`)
      return
    }
    setEditingSource(null)
    form.resetFields()
    form.setFieldsValue({
      paywall_enabled: false,
      x_cookie_enabled: sharedXAuthConfigs.length > 0,
      x_auth_mode: sharedXAuthConfigs.length > 0 ? 'shared' : 'dedicated',
      x_shared_auth_config_id: defaultSharedXAuthConfigId,
      auth_type: 'password',
    })
    setIsModalOpen(true)
  }

  const handleTypeChange = (nextType: SourceType) => {
    if (editingSource) return
    if (nextType === 'x') {
      form.setFieldsValue({
        x_cookie_enabled: sharedXAuthConfigs.length > 0,
        x_auth_mode: sharedXAuthConfigs.length > 0 ? 'shared' : 'dedicated',
        x_shared_auth_config_id: defaultSharedXAuthConfigId,
      })
      return
    }
    form.setFieldsValue({
      x_cookie_enabled: false,
      x_auth_mode: sharedXAuthConfigs.length > 0 ? 'shared' : 'dedicated',
      x_shared_auth_config_id: undefined,
      x_auth_name: undefined,
      x_auth_token: undefined,
      x_ct0: undefined,
    })
  }

  return {
    isModalOpen,
    setIsModalOpen,
    editingSource,
    setEditingSource,
    form,
    createMutation,
    updateMutation,
    deleteMutation,
    fetchMutation,
    probeMutation,
    probeAllMutation,
    handleSubmit,
    handleEdit,
    handleAdd,
    handleTypeChange,
    matchAuthConfigByHost,
  }
}
```

- [ ] **Step 4: 验证测试通过**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/frontend && npm test -- --run src/components/SourceList/hooks/useSourceEditor.test.ts 2>&1 | tail -20
```

Expected: 所有测试通过

- [ ] **Step 5: 运行 lint**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/frontend && npm run lint 2>&1 | tail -20
```

Expected: 无报错

- [ ] **Step 6: Commit**

```bash
cd /Users/shuhuaiwang/personal-info-monitor && git add frontend/src/components/SourceList/hooks/useSourceEditor.ts frontend/src/components/SourceList/hooks/useSourceEditor.test.ts && git commit -m "feat: add useSourceEditor hook encapsulating editor modal state and CRUD mutations"
```

---

### Task 4: 实现 useSourceImport hook

**Files:**
- Create: `frontend/src/components/SourceList/hooks/useSourceImport.ts`
- Create: `frontend/src/components/SourceList/hooks/useSourceImport.test.ts`

**背景：** 将 SourceManager.tsx 中批量导入相关逻辑提取：`isImportModalOpen`、`importPreview`、`isImporting`、`fileInputRef`、`bulkImportMutation`、`handleFileSelect`、`handleBulkImport`。

- [ ] **Step 1: 先写测试文件**

创建 `frontend/src/components/SourceList/hooks/useSourceImport.test.ts`：

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('../../../services/sources', () => ({
  sourcesApi: { bulkImport: vi.fn() },
}))
vi.mock('../../../services/queryKeys', () => ({
  sourceKeys: { all: ['sources'] },
}))
vi.mock('../importUtils', () => ({
  detectSourceType: vi.fn(() => 'website'),
  parseCSV: vi.fn(() => [{ name: 'Test', description: '', url: 'https://example.com' }]),
  parseUrlLines: vi.fn(() => []),
}))

import { useSourceImport } from './useSourceImport'

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return React.createElement(QueryClientProvider, { client: qc }, children)
}

describe('useSourceImport', () => {
  beforeEach(() => vi.clearAllMocks())

  it('initialises with isImportModalOpen=false and importPreview=[]', () => {
    const { result } = renderHook(() => useSourceImport({ remainingSources: 100 }), { wrapper })
    expect(result.current.isImportModalOpen).toBe(false)
    expect(result.current.importPreview).toHaveLength(0)
  })

  it('isImporting starts false', () => {
    const { result } = renderHook(() => useSourceImport({ remainingSources: 100 }), { wrapper })
    expect(result.current.isImporting).toBe(false)
  })

  it('handleBulkImport exits early when importPreview is empty', async () => {
    const { sourcesApi } = await import('../../../services/sources')
    const { result } = renderHook(() => useSourceImport({ remainingSources: 100 }), { wrapper })
    await act(async () => { await result.current.handleBulkImport() })
    expect(sourcesApi.bulkImport).not.toHaveBeenCalled()
  })

  it('closing the modal clears importPreview', () => {
    const { result } = renderHook(() => useSourceImport({ remainingSources: 100 }), { wrapper })
    act(() => {
      result.current.setImportPreview([{ name: 'A', description: '', url: 'https://a.com', type: 'website' }])
      result.current.setIsImportModalOpen(false)
    })
    // After close, consumer can call setImportPreview([]) - hook exposes both setters
    act(() => { result.current.setImportPreview([]) })
    expect(result.current.importPreview).toHaveLength(0)
  })
})
```

- [ ] **Step 2: 验证测试失败**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/frontend && npm test -- --run src/components/SourceList/hooks/useSourceImport.test.ts 2>&1 | tail -20
```

Expected: 测试因找不到 `./useSourceImport` 而报错

- [ ] **Step 3: 实现 useSourceImport.ts**

创建 `frontend/src/components/SourceList/hooks/useSourceImport.ts`：

```ts
import { useState, useRef } from 'react'
import { message } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { sourcesApi } from '../../../services/sources'
import { sourceKeys } from '../../../services/queryKeys'
import type { SourceCreate } from '../../../types'
import { detectSourceType, parseCSV, type ImportPreviewItem } from '../importUtils'

interface UseSourceImportOptions {
  remainingSources: number
}

export function useSourceImport({ remainingSources }: UseSourceImportOptions) {
  const [isImportModalOpen, setIsImportModalOpen] = useState(false)
  const [importPreview, setImportPreview] = useState<ImportPreviewItem[]>([])
  const [isImporting, setIsImporting] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()

  const bulkImportMutation = useMutation({
    mutationFn: sourcesApi.bulkImport,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: sourceKeys.all })
      message.success(`成功导入 ${data.length} 个监控源`)
      setIsImportModalOpen(false)
      setImportPreview([])
    },
    onError: () => {
      message.error('导入失败')
    },
  })

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (e) => {
      const content = e.target?.result as string
      const parsed = parseCSV(content)
      const preview: ImportPreviewItem[] = parsed.map((item) => ({
        ...item,
        type: detectSourceType(item.url),
      }))
      setImportPreview(preview)
      setIsImportModalOpen(true)
    }
    reader.readAsText(file, 'UTF-8')

    // Reset so the same file can be re-selected
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleBulkImport = async () => {
    if (importPreview.length === 0) return
    if (importPreview.length > remainingSources) {
      message.error(
        `导入失败：还可新增 ${remainingSources} 个信源，本次准备导入 ${importPreview.length} 个。`
      )
      return
    }

    setIsImporting(true)

    const sourcesToImport: SourceCreate[] = importPreview.map((item) => ({
      name: item.name,
      type: item.type,
      url: item.url,
      metadata: item.description ? { description: item.description } : undefined,
      fetch_interval: 60,
      enabled: true,
      priority: 0,
    }))

    try {
      await bulkImportMutation.mutateAsync(sourcesToImport)
    } finally {
      setIsImporting(false)
    }
  }

  return {
    isImportModalOpen,
    setIsImportModalOpen,
    importPreview,
    setImportPreview,
    isImporting,
    fileInputRef,
    bulkImportMutation,
    handleFileSelect,
    handleBulkImport,
  }
}
```

- [ ] **Step 4: 验证测试通过**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/frontend && npm test -- --run src/components/SourceList/hooks/useSourceImport.test.ts 2>&1 | tail -20
```

Expected: 所有测试通过

- [ ] **Step 5: 运行 lint**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/frontend && npm run lint 2>&1 | tail -20
```

Expected: 无报错

- [ ] **Step 6: Commit**

```bash
cd /Users/shuhuaiwang/personal-info-monitor && git add frontend/src/components/SourceList/hooks/useSourceImport.ts frontend/src/components/SourceList/hooks/useSourceImport.test.ts && git commit -m "feat: add useSourceImport hook encapsulating CSV import state and bulk-import mutation"
```

---

### Task 5: 实现 SourceEditorModal 组件

**Files:**
- Create: `frontend/src/components/SourceList/SourceEditorModal.tsx`

**背景：** 将 SourceManager.tsx 第 941–1234 行的 `<Modal>` 编辑/新增表单提取为独立组件。该组件为纯展示层（controlled），不持有任何状态，所有 state 和回调均由父层（SourceListContainer）通过 props 传入。

- [ ] **Step 1: 创建 SourceEditorModal.tsx**

创建 `frontend/src/components/SourceList/SourceEditorModal.tsx`：

```tsx
import React from 'react'
import {
  Modal,
  Form,
  Input,
  Select,
  Switch,
  Space,
  Button,
  InputNumber,
  Divider,
} from 'antd'
import type { FormInstance } from 'antd'
import type { Source, Category, SourceType } from '../../types'
import type { AuthConfig } from '../../services/configs'
import { PODCAST_SOURCES_ENABLED } from '../../config/features'
import { getAuthConfigDisplayName } from './hooks/useSourceEditor'
import SectionNote from '../ui/SectionNote'

const { Option } = Select

interface SourceEditorModalProps {
  open: boolean
  editingSource: Source | null
  form: FormInstance
  categories: Category[] | undefined
  sharedXAuthConfigs: AuthConfig[]
  isSubmitting: boolean
  onTypeChange: (type: SourceType) => void
  onSubmit: (values: any) => void
  onClose: () => void
}

const SourceEditorModal: React.FC<SourceEditorModalProps> = ({
  open,
  editingSource,
  form,
  categories,
  sharedXAuthConfigs,
  isSubmitting,
  onTypeChange,
  onSubmit,
  onClose,
}) => {
  return (
    <Modal
      title={editingSource ? '编辑监控源' : '添加监控源'}
      open={open}
      onCancel={onClose}
      footer={null}
      width={600}
    >
      <Form form={form} layout="vertical" onFinish={onSubmit}>
        <Form.Item
          name="name"
          label="名称"
          rules={[{ required: true, message: '请输入名称' }]}
        >
          <Input placeholder="例如：TechCrunch" />
        </Form.Item>

        <Form.Item
          name="type"
          label="类型"
          rules={[{ required: true, message: '请选择类型' }]}
        >
          <Select placeholder="选择类型" onChange={onTypeChange}>
            <Option value="website">网站/博客</Option>
            <Option value="rss">RSS</Option>
            <Option value="x">X (Twitter)</Option>
            <Option value="youtube">YouTube</Option>
            {PODCAST_SOURCES_ENABLED ? <Option value="podcast">播客</Option> : null}
          </Select>
        </Form.Item>

        <Form.Item
          name="url"
          label="URL"
          rules={[
            { required: true, message: '请输入URL' },
            { type: 'url', message: '请输入有效的URL' },
          ]}
        >
          <Input placeholder="https://example.com/feed" />
        </Form.Item>

        <Form.Item
          name="extra_urls_text"
          label="附加 URL（可选）"
          tooltip="每行一个 URL，用于同一信源下抓取多个频道/列表页"
        >
          <Input.TextArea
            placeholder={"https://example.com/channel/a\nhttps://example.com/channel/b"}
            autoSize={{ minRows: 3, maxRows: 6 }}
          />
        </Form.Item>

        <Divider style={{ marginTop: 8, marginBottom: 12 }}>访问凭证</Divider>
        <Form.Item shouldUpdate noStyle>
          {() => {
            const currentType = form.getFieldValue('type')
            if (currentType !== 'website' && currentType !== 'x') return null
            if (currentType === 'x') {
              return (
                <>
                  <Form.Item
                    name="x_cookie_enabled"
                    label="启用 X 登录态"
                    valuePropName="checked"
                    initialValue={false}
                  >
                    <Switch checkedChildren="启用" unCheckedChildren="关闭" />
                  </Form.Item>

                  <Form.Item shouldUpdate noStyle>
                    {() => {
                      const xCookieEnabled = form.getFieldValue('x_cookie_enabled')
                      if (!xCookieEnabled) return null
                      const xAuthMode =
                        form.getFieldValue('x_auth_mode') ||
                        (sharedXAuthConfigs.length > 0 ? 'shared' : 'dedicated')
                      return (
                        <>
                          <SectionNote style={{ marginBottom: 12 }}>
                            平台级 API 凭证仍在"采集凭证"页维护。X 登录态默认建议复用共享配置，只有少数特殊源再单独覆盖。
                          </SectionNote>
                          <Form.Item
                            name="x_auth_mode"
                            label="登录态来源"
                            initialValue={sharedXAuthConfigs.length > 0 ? 'shared' : 'dedicated'}
                          >
                            <Select>
                              <Option value="shared">复用共享 X 登录态</Option>
                              <Option value="dedicated">仅当前源单独配置</Option>
                            </Select>
                          </Form.Item>

                          {xAuthMode === 'shared' ? (
                            <>
                              <Form.Item
                                name="x_shared_auth_config_id"
                                label="共享 X 登录态"
                                rules={[{ required: true, message: '请选择共享 X 登录态' }]}
                              >
                                <Select
                                  placeholder={
                                    sharedXAuthConfigs.length > 0
                                      ? '选择一个共享 X 登录态'
                                      : '请先到"采集凭证"页添加共享 X 登录态'
                                  }
                                  options={sharedXAuthConfigs.map((config) => ({
                                    value: config.id,
                                    label: `${getAuthConfigDisplayName(config)} (${config.bound_source_count || 0} 个源)`,
                                  }))}
                                />
                              </Form.Item>
                              {sharedXAuthConfigs.length === 0 ? (
                                <SectionNote tone="caution" style={{ marginBottom: 12 }}>
                                  当前还没有共享 X 登录态。你可以先去"采集凭证"页添加，或者改为"仅当前源单独配置"。
                                </SectionNote>
                              ) : null}
                            </>
                          ) : (
                            <>
                              <SectionNote tone="caution" style={{ marginBottom: 12 }}>
                                专用 X 登录态只绑定到当前监控源，适合少数需要独立账号或独立 Cookie 的例外场景。
                              </SectionNote>
                              <Form.Item name="x_auth_name" label="专用登录态名称（可选）">
                                <Input placeholder="例如：某个敏感信源专用账号" />
                              </Form.Item>
                              <Form.Item name="x_auth_token" label="auth_token">
                                <Input.Password
                                  placeholder={editingSource ? '留空则不更新' : '输入 auth_token'}
                                  autoComplete="off"
                                />
                              </Form.Item>
                              <Form.Item name="x_ct0" label="ct0">
                                <Input.Password
                                  placeholder={editingSource ? '留空则不更新' : '输入 ct0'}
                                  autoComplete="off"
                                />
                              </Form.Item>
                            </>
                          )}
                        </>
                      )
                    }}
                  </Form.Item>
                </>
              )
            }
            return (
              <>
                <Form.Item
                  name="paywall_enabled"
                  label="启用站点登录态 / 付费墙凭证"
                  valuePropName="checked"
                  initialValue={false}
                >
                  <Switch checkedChildren="启用" unCheckedChildren="关闭" />
                </Form.Item>

                <Form.Item shouldUpdate noStyle>
                  {() => {
                    const paywallEnabled = form.getFieldValue('paywall_enabled')
                    if (!paywallEnabled) return null
                    return (
                      <>
                        <SectionNote style={{ marginBottom: 12 }}>
                          站点凭证只绑定到当前监控源；有 Cookie 时，系统会优先抓取站内直达文章链接，再回退 RSS。
                        </SectionNote>
                        <Form.Item name="auth_type" label="认证方式" initialValue="password">
                          <Select>
                            <Option value="password">用户名密码 + Cookie</Option>
                            <Option value="cookie">Cookie</Option>
                            <Option value="api_key">API Key</Option>
                          </Select>
                        </Form.Item>
                        <Form.Item name="login_url" label="登录页面 URL">
                          <Input placeholder="https://example.com/login" />
                        </Form.Item>
                        <Form.Item name="username" label="用户名">
                          <Input placeholder={editingSource ? '留空则不更新' : ''} />
                        </Form.Item>
                        <Form.Item name="password" label="密码">
                          <Input.Password placeholder={editingSource ? '留空则不更新' : ''} />
                        </Form.Item>
                        <Form.Item
                          name="cookies"
                          label="Cookie（整行粘贴）"
                          tooltip="支持 name1=value1; name2=value2 格式"
                        >
                          <Input.TextArea
                            rows={4}
                            placeholder="例如：wsjregion=na,us; DJSESSIONID=xxx; ..."
                          />
                        </Form.Item>
                      </>
                    )
                  }}
                </Form.Item>
              </>
            )
          }}
        </Form.Item>

        <Form.Item name="category_id" label="分类">
          <Select placeholder="选择分类" allowClear>
            {categories?.map((cat: Category) => (
              <Option key={cat.id} value={cat.id}>
                {cat.name}
              </Option>
            ))}
          </Select>
        </Form.Item>

        <Form.Item name="fetch_interval" label="抓取间隔（分钟）" initialValue={60}>
          <InputNumber min={15} max={1440} style={{ width: '100%' }} />
        </Form.Item>

        <Divider style={{ marginTop: 8, marginBottom: 12 }}>内容过滤</Divider>
        <Form.Item
          name="use_keyword_filter"
          label="启用关键词过滤"
          valuePropName="checked"
          initialValue={false}
          tooltip="开启后，只有标题或正文匹配至少一个关键词的内容才会被保存。需先在「设置 → 关键词管理」中配置关键词。"
        >
          <Switch checkedChildren="过滤" unCheckedChildren="全量" />
        </Form.Item>
        <Form.Item shouldUpdate noStyle>
          {() => {
            const filterEnabled = form.getFieldValue('use_keyword_filter')
            if (!filterEnabled) return null
            return (
              <SectionNote style={{ marginBottom: 12 }}>
                已启用关键词过滤：仅标题或正文匹配关键词的内容会被抓取保存，未匹配内容将被跳过。请确保已在「设置 → 关键词管理」中添加关键词。
              </SectionNote>
            )
          }}
        </Form.Item>

        <Form.Item name="enabled" label="启用" valuePropName="checked" initialValue={true}>
          <Switch />
        </Form.Item>

        <Form.Item name="priority" label="优先级" initialValue={0}>
          <InputNumber min={0} max={100} style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={isSubmitting}>
              {editingSource ? '更新' : '创建'}
            </Button>
            <Button onClick={onClose}>取消</Button>
          </Space>
        </Form.Item>
      </Form>
    </Modal>
  )
}

export default SourceEditorModal
```

- [ ] **Step 2: 运行 lint 验证**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/frontend && npm run lint 2>&1 | tail -20
```

Expected: 无报错

- [ ] **Step 3: Commit**

```bash
cd /Users/shuhuaiwang/personal-info-monitor && git add frontend/src/components/SourceList/SourceEditorModal.tsx && git commit -m "feat: add SourceEditorModal component as controlled view-only modal"
```

---

### Task 6: 实现 SourceImportModal 组件

**Files:**
- Create: `frontend/src/components/SourceList/SourceImportModal.tsx`

**背景：** 将 SourceManager.tsx 第 1236–1294 行的导入预览 `<Modal>` 提取为独立组件，完全受控，不持有状态。

- [ ] **Step 1: 创建 SourceImportModal.tsx**

创建 `frontend/src/components/SourceList/SourceImportModal.tsx`：

```tsx
import React from 'react'
import { Modal, Table, Button, Tag } from 'antd'
import type { ImportPreviewItem } from './importUtils'
import type { SourceType } from '../../types'
import SectionNote from '../ui/SectionNote'

const typeColors: Record<string, string> = {
  website: 'blue',
  rss: 'gold',
  x: 'cyan',
  youtube: 'red',
}

const importColumns = [
  { title: '名称', dataIndex: 'name', key: 'name', width: 200 },
  {
    title: '类型',
    dataIndex: 'type',
    key: 'type',
    width: 100,
    render: (type: SourceType) => <Tag color={typeColors[type] || 'default'}>{type}</Tag>,
  },
  { title: 'URL', dataIndex: 'url', key: 'url', ellipsis: true },
  { title: '简介', dataIndex: 'description', key: 'description', ellipsis: true, width: 200 },
]

interface SourceImportModalProps {
  open: boolean
  importPreview: ImportPreviewItem[]
  isImporting: boolean
  remainingSources: number
  onImport: () => void
  onClose: () => void
}

const SourceImportModal: React.FC<SourceImportModalProps> = ({
  open,
  importPreview,
  isImporting,
  remainingSources,
  onImport,
  onClose,
}) => {
  return (
    <Modal
      title={`导入预览 (${importPreview.length} 条)`}
      open={open}
      onCancel={onClose}
      width={900}
      footer={[
        <Button key="cancel" onClick={onClose} disabled={isImporting}>
          取消
        </Button>,
        <Button
          key="import"
          type="primary"
          loading={isImporting}
          onClick={onImport}
          disabled={importPreview.length === 0 || importPreview.length > remainingSources}
        >
          确认导入 ({importPreview.length} 条)
        </Button>,
      ]}
    >
      {importPreview.length > remainingSources ? (
        <SectionNote tone="caution" style={{ marginBottom: 12 }}>
          {`当前最多还能导入 ${remainingSources} 个信源，请减少本次导入数量。`}
        </SectionNote>
      ) : null}
      {isImporting && (
        <SectionNote style={{ marginBottom: 16 }}>
          {`正在导入 ${importPreview.length} 条信源，请稍候...`}
        </SectionNote>
      )}
      <Table
        columns={importColumns}
        dataSource={importPreview}
        rowKey={(record) => record.url}
        size="small"
        pagination={{ pageSize: 10 }}
        scroll={{ y: 400 }}
      />
      <div style={{ marginTop: 16, color: '#666', fontSize: 13 }}>
        <p style={{ marginBottom: 8 }}>* 系统会根据 URL 自动检测监控源类型：</p>
        <ul style={{ marginLeft: 20 }}>
          <li><Tag color="red">youtube</Tag> - YouTube 链接</li>
          <li><Tag color="cyan">x</Tag> - X (Twitter) 链接</li>
          <li><Tag color="gold">rss</Tag> - RSS/Feed 链接</li>
          <li><Tag color="blue">website</Tag> - 其他网站</li>
        </ul>
      </div>
    </Modal>
  )
}

export default SourceImportModal
```

- [ ] **Step 2: 运行 lint 验证**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/frontend && npm run lint 2>&1 | tail -20
```

Expected: 无报错

- [ ] **Step 3: Commit**

```bash
cd /Users/shuhuaiwang/personal-info-monitor && git add frontend/src/components/SourceList/SourceImportModal.tsx && git commit -m "feat: add SourceImportModal component as controlled import preview modal"
```

---

### Task 7: 实现 SourceListContainer 组件

**Files:**
- Create: `frontend/src/components/SourceList/SourceListContainer.tsx`

**背景：** 这是重构后真正的"逻辑层"。它组合三个 hooks，渲染工具栏、表格、批量操作栏，并将 props 传给两个 Modal 组件。不含内联 JSX 的 Modal 表单定义（已在 Task 5/6 中移出）。

- [ ] **Step 1: 创建 SourceListContainer.tsx**

创建 `frontend/src/components/SourceList/SourceListContainer.tsx`：

```tsx
import React from 'react'
import {
  Table,
  Button,
  Space,
  Tag,
  Popconfirm,
  message,
  Alert,
  Empty,
  Input,
  Tooltip,
} from 'antd'
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  SyncOutlined,
  UploadOutlined,
  RadarChartOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { sourcesApi } from '../../services/sources'
import { sourceKeys } from '../../services/queryKeys'
import { isXCookieProfile, getDefaultSharedXAuthConfigId } from '../../utils/sourceAuth'
import type { Source, SourceType } from '../../types'
import { formatLocalDateTime } from '../../utils/datetime'
import FetchStatusIcon from './FetchStatusIcon'
import SectionNote from '../ui/SectionNote'
import SourceEditorModal from './SourceEditorModal'
import SourceImportModal from './SourceImportModal'
import { useSourceList, typeFilters } from './hooks/useSourceList'
import { useSourceEditor } from './hooks/useSourceEditor'
import { useSourceImport } from './hooks/useSourceImport'

const typeColors: Record<string, string> = {
  website: 'blue',
  rss: 'gold',
  x: 'cyan',
  youtube: 'red',
}

const strategyLabels: Record<string, string> = {
  rss: 'RSS',
  scrape: '网页抓取',
  js: 'JS渲染',
  rsshub: 'RSSHub',
  nitter: 'Nitter',
  api: '官方API',
  none: '-',
  unknown: '-',
}

const SourceListContainer: React.FC = () => {
  const queryClient = useQueryClient()

  const listState = useSourceList()
  const {
    activeTypeFilter,
    setActiveTypeFilter,
    searchInput,
    setSearchInput,
    debouncedSearch,
    page,
    setPage,
    pageSize,
    setPageSize,
    selectedRowKeys,
    setSelectedRowKeys,
    sources,
    listData,
    isLoading,
    isError,
    isFetching,
    refetchSources,
    categories,
    authConfigs,
    sourceCount,
    maxSources,
    remainingSources,
    sourceLimitReached,
    sourceLoadError,
    getTypeCount,
  } = listState

  const sharedXAuthConfigs = (authConfigs || []).filter(
    (config) => config.is_shared && isXCookieProfile(config)
  )
  const defaultSharedXAuthConfigId = getDefaultSharedXAuthConfigId(sharedXAuthConfigs)

  const editorState = useSourceEditor({
    authConfigs: authConfigs || [],
    sourceLimitReached,
    maxSources,
    remainingSources,
    sharedXAuthConfigs,
    defaultSharedXAuthConfigId,
  })
  const {
    isModalOpen,
    setIsModalOpen,
    editingSource,
    setEditingSource,
    form,
    createMutation,
    updateMutation,
    deleteMutation,
    fetchMutation,
    probeMutation,
    probeAllMutation,
    handleSubmit,
    handleEdit,
    handleAdd,
    handleTypeChange,
  } = editorState

  const importState = useSourceImport({ remainingSources })
  const {
    isImportModalOpen,
    setIsImportModalOpen,
    importPreview,
    setImportPreview,
    isImporting,
    fileInputRef,
    handleFileSelect,
    handleBulkImport,
  } = importState

  const handleBulkDelete = async () => {
    if (selectedRowKeys.length === 0) return
    try {
      await Promise.all(selectedRowKeys.map((id) => sourcesApi.delete(id as string)))
      queryClient.invalidateQueries({ queryKey: sourceKeys.all })
      message.success(`成功删除 ${selectedRowKeys.length} 个监控源`)
      setSelectedRowKeys([])
    } catch {
      message.error('批量删除失败')
    }
  }

  const handleBulkFetch = async () => {
    if (selectedRowKeys.length === 0) return
    try {
      await Promise.all(selectedRowKeys.map((id) => sourcesApi.triggerFetch(id as string)))
      message.success(`已触发 ${selectedRowKeys.length} 个监控源的抓取任务`)
    } catch {
      message.error('批量抓取失败')
    }
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name', width: 180 },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 100,
      render: (type: string) => <Tag color={typeColors[type] || 'default'}>{type}</Tag>,
    },
    {
      title: '可抓取',
      key: 'fetch_status',
      width: 80,
      align: 'center' as const,
      sorter: (a: Source, b: Source) => {
        const order: Record<string, number> = { ok: 0, warning: 1, error: 2, unknown: 3 }
        return (order[a.fetch_status] ?? 3) - (order[b.fetch_status] ?? 3)
      },
      render: (_: unknown, record: Source) => (
        <FetchStatusIcon
          status={record.fetch_status}
          message={record.fetch_status_message}
          strategy={record.fetch_strategy}
        />
      ),
    },
    {
      title: '策略',
      key: 'fetch_strategy',
      width: 90,
      render: (_: unknown, record: Source) => (
        <span style={{ fontSize: 12, color: '#666' }}>
          {strategyLabels[record.fetch_strategy] || record.fetch_strategy || '-'}
        </span>
      ),
    },
    {
      title: 'URL',
      dataIndex: 'url',
      key: 'url',
      ellipsis: true,
      render: (url: string, record: Source) => (
        <>
          <a href={url} target="_blank" rel="noopener noreferrer">{url}</a>
          {Array.isArray(record.extra_urls) && record.extra_urls.length > 0 ? (
            <span style={{ marginLeft: 8, color: '#999', fontSize: 12 }}>
              + {record.extra_urls.length} 个附加 URL
            </span>
          ) : null}
        </>
      ),
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 70,
      render: (enabled: boolean, record: Source) => (
        <Space size={4}>
          <Tag color={enabled ? 'green' : 'default'}>{enabled ? '启用' : '禁用'}</Tag>
          {record.use_keyword_filter && <Tag color="orange">过滤</Tag>}
        </Space>
      ),
    },
    {
      title: '最后抓取',
      dataIndex: 'last_fetched_at',
      key: 'last_fetched_at',
      width: 160,
      render: (time: string | null) => (time ? formatLocalDateTime(time, 'zh-CN') : '-'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 240,
      render: (_: unknown, record: Source) => (
        <Space>
          <Tooltip title="探测可抓取性">
            <Button
              icon={<RadarChartOutlined />}
              size="small"
              onClick={() => probeMutation.mutate(record.id)}
              loading={probeMutation.isPending && probeMutation.variables === record.id}
            />
          </Tooltip>
          <Button icon={<SyncOutlined />} size="small" onClick={() => fetchMutation.mutate(record.id)}>
            抓取
          </Button>
          <Button icon={<EditOutlined />} size="small" onClick={() => handleEdit(record)}>
            编辑
          </Button>
          <Popconfirm
            title="确定要删除这个监控源吗？"
            onConfirm={() => deleteMutation.mutate(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Button icon={<DeleteOutlined />} size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const rowSelection = {
    selectedRowKeys,
    onChange: (keys: React.Key[]) => setSelectedRowKeys(keys),
  }

  return (
    <div data-testid="source-manager">
      <input
        type="file"
        accept=".csv"
        ref={fileInputRef}
        style={{ display: 'none' }}
        onChange={handleFileSelect}
      />

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 12,
          marginBottom: 16,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', gap: 0, flexWrap: 'wrap' }}>
          {typeFilters.map((filter, idx) => (
            <button
              key={filter.key}
              onClick={() => { setActiveTypeFilter(filter.key); setSelectedRowKeys([]) }}
              data-testid={`source-filter-${filter.key}`}
              style={{
                padding: '10px 16px',
                fontSize: 14,
                fontWeight: activeTypeFilter === filter.key ? 600 : 400,
                color: activeTypeFilter === filter.key ? '#6b7c3f' : '#666',
                backgroundColor: activeTypeFilter === filter.key ? '#f5f8ef' : 'transparent',
                border: '1px solid #eee',
                borderRight: idx === typeFilters.length - 1 ? '1px solid #eee' : 'none',
                cursor: 'pointer',
              }}
            >
              {filter.label}
              <span style={{ marginLeft: 6, fontSize: 12, color: '#999' }}>
                ({getTypeCount(filter.key)})
              </span>
            </button>
          ))}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <Tooltip title="检测所有源的可抓取性">
            <Button
              icon={<RadarChartOutlined />}
              onClick={() => probeAllMutation.mutate()}
              loading={probeAllMutation.isPending}
              size="small"
            >
              全部探测
            </Button>
          </Tooltip>
          <Button
            icon={<UploadOutlined />}
            onClick={() => fileInputRef.current?.click()}
            size="small"
            disabled={sourceLimitReached}
          >
            导入 CSV
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleAdd}
            size="small"
            disabled={sourceLimitReached}
            style={{ backgroundColor: '#6b7c3f', borderColor: '#6b7c3f' }}
          >
            添加监控源
          </Button>
          <Input
            allowClear
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="搜索信源名称或 URL"
            prefix={<SearchOutlined style={{ color: '#999' }} />}
            data-testid="source-search-input"
            style={{ width: 240 }}
          />
        </div>
      </div>

      <SectionNote
        tone={sourceLimitReached ? 'caution' : 'neutral'}
        style={{ marginBottom: 12 }}
      >
        {sourceLimitReached
          ? `监控源数量已达上限（${sourceCount}/${maxSources}）。新增和批量导入会被阻止。`
          : `监控源配额：${sourceCount}/${maxSources}，还可新增 ${remainingSources} 个。`}
      </SectionNote>

      {isError && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message="信源库加载失败"
          description={sourceLoadError}
          action={
            <Button size="small" onClick={() => refetchSources()} loading={isFetching}>
              重新加载
            </Button>
          }
        />
      )}

      {selectedRowKeys.length > 0 && (
        <div
          style={{
            marginBottom: 16,
            padding: '8px 12px',
            backgroundColor: '#fafafa',
            border: '1px solid #eee',
            borderRadius: 6,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: 8,
          }}
        >
          <span style={{ fontSize: 13, color: '#666' }}>
            已选 <strong style={{ color: '#6b7c3f' }}>{selectedRowKeys.length}</strong> 项
          </span>
          <Space>
            <Button
              icon={<RadarChartOutlined />}
              size="small"
              onClick={async () => {
                await Promise.all(selectedRowKeys.map((id) => sourcesApi.probeSource(id as string)))
                queryClient.invalidateQueries({ queryKey: sourceKeys.all })
                message.success(`已探测 ${selectedRowKeys.length} 个源`)
              }}
            >
              批量探测
            </Button>
            <Button icon={<SyncOutlined />} size="small" onClick={handleBulkFetch}>
              批量抓取
            </Button>
            <Popconfirm
              title={`确定要删除选中的 ${selectedRowKeys.length} 个监控源吗？`}
              onConfirm={handleBulkDelete}
              okText="确定"
              cancelText="取消"
            >
              <Button icon={<DeleteOutlined />} size="small" danger>批量删除</Button>
            </Popconfirm>
          </Space>
        </div>
      )}

      <div data-testid="source-table">
        <Table
          rowSelection={rowSelection}
          columns={columns}
          dataSource={sources}
          loading={isLoading}
          rowKey="id"
          locale={{
            emptyText: (
              <Empty
                description={
                  isError
                    ? '信源数据暂时加载失败'
                    : debouncedSearch || activeTypeFilter !== 'all'
                      ? '没有匹配的信源'
                      : '暂无信源'
                }
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              />
            ),
          }}
          pagination={{
            current: page,
            pageSize,
            total: listData?.total ?? 0,
            onChange: (p, ps) => { setPage(p); setPageSize(ps ?? 20) },
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 个信源`,
          }}
          style={{ backgroundColor: '#fff' }}
        />
      </div>

      <SourceEditorModal
        open={isModalOpen}
        editingSource={editingSource}
        form={form}
        categories={categories}
        sharedXAuthConfigs={sharedXAuthConfigs}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
        onTypeChange={handleTypeChange as (type: SourceType) => void}
        onSubmit={handleSubmit}
        onClose={() => {
          setIsModalOpen(false)
          setEditingSource(null)
          form.resetFields()
        }}
      />

      <SourceImportModal
        open={isImportModalOpen}
        importPreview={importPreview}
        isImporting={isImporting}
        remainingSources={remainingSources}
        onImport={handleBulkImport}
        onClose={() => { setIsImportModalOpen(false); setImportPreview([]) }}
      />
    </div>
  )
}

export default SourceListContainer
```

- [ ] **Step 2: 运行 lint 验证**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/frontend && npm run lint 2>&1 | tail -30
```

Expected: 无报错

- [ ] **Step 3: Commit**

```bash
cd /Users/shuhuaiwang/personal-info-monitor && git add frontend/src/components/SourceList/SourceListContainer.tsx && git commit -m "feat: add SourceListContainer composing three hooks with toolbar/table/modals"
```

---

### Task 8: 将 SourceManager.tsx 改为薄壳，验证完整性

**Files:**
- Modify: `frontend/src/components/SourceList/SourceManager.tsx`

**背景：** 将原 1299 行的 SourceManager.tsx 整体替换为一个薄壳组件，只 import 并渲染 `<SourceListContainer />`。对外接口（组件名、default export）保持不变，Settings.tsx 无需修改，Settings.test.tsx 的 mock 也无需调整。

- [ ] **Step 1: 替换 SourceManager.tsx 为薄壳**

将 `frontend/src/components/SourceList/SourceManager.tsx` 全部内容替换为：

```tsx
import React from 'react'
import SourceListContainer from './SourceListContainer'

/**
 * SourceManager — 对外保持原接口不变。
 * 内部逻辑已拆分到 SourceListContainer + useSourceList / useSourceEditor / useSourceImport。
 */
const SourceManager: React.FC = () => <SourceListContainer />

export default SourceManager
```

- [ ] **Step 2: 运行全量测试**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/frontend && npm test -- --run 2>&1 | tail -40
```

Expected: 所有测试通过（包括 Settings.test.tsx、importUtils.test.ts、sourceAuth.test.ts、三个 hook 测试）

- [ ] **Step 3: 运行 lint**

```bash
cd /Users/shuhuaiwang/personal-info-monitor/frontend && npm run lint 2>&1 | tail -20
```

Expected: 无报错

- [ ] **Step 4: 验证文件行数符合预期**

```bash
wc -l /Users/shuhuaiwang/personal-info-monitor/frontend/src/components/SourceList/SourceManager.tsx \
       /Users/shuhuaiwang/personal-info-monitor/frontend/src/components/SourceList/SourceListContainer.tsx \
       /Users/shuhuaiwang/personal-info-monitor/frontend/src/components/SourceList/SourceEditorModal.tsx \
       /Users/shuhuaiwang/personal-info-monitor/frontend/src/components/SourceList/SourceImportModal.tsx \
       /Users/shuhuaiwang/personal-info-monitor/frontend/src/components/SourceList/hooks/useSourceList.ts \
       /Users/shuhuaiwang/personal-info-monitor/frontend/src/components/SourceList/hooks/useSourceEditor.ts \
       /Users/shuhuaiwang/personal-info-monitor/frontend/src/components/SourceList/hooks/useSourceImport.ts \
       /Users/shuhuaiwang/personal-info-monitor/frontend/src/utils/sourceAuth.ts
```

Expected: SourceManager.tsx 应约 10 行；各文件行数均远小于原始 1299 行

- [ ] **Step 5: 最终 commit**

```bash
cd /Users/shuhuaiwang/personal-info-monitor && git add frontend/src/components/SourceList/SourceManager.tsx && git commit -m "refactor: reduce SourceManager.tsx to thin shell delegating to SourceListContainer"
```

---

## 验收标准

完成全部 8 个 Task 后，运行以下命令进行最终验收：

```bash
cd /Users/shuhuaiwang/personal-info-monitor/frontend && npm test -- --run && npm run lint
```

- 全量测试通过（包括 Settings.test.tsx 对 SourceManager mock 不受影响）
- lint 无报错
- 新增文件结构与计划一致：
  - `frontend/src/utils/sourceAuth.ts` + `sourceAuth.test.ts`
  - `frontend/src/components/SourceList/SourceManager.tsx`（薄壳，约 10 行）
  - `frontend/src/components/SourceList/SourceListContainer.tsx`
  - `frontend/src/components/SourceList/SourceEditorModal.tsx`
  - `frontend/src/components/SourceList/SourceImportModal.tsx`
  - `frontend/src/components/SourceList/hooks/useSourceList.ts` + `useSourceList.test.ts`
  - `frontend/src/components/SourceList/hooks/useSourceEditor.ts` + `useSourceEditor.test.ts`
  - `frontend/src/components/SourceList/hooks/useSourceImport.ts` + `useSourceImport.test.ts`
- `frontend/src/components/Settings/APIKeysTab.tsx` 中不再有 `normalizeHost` / `isXCookieProfile` 本地定义，改为从 `../../utils/sourceAuth` 导入
