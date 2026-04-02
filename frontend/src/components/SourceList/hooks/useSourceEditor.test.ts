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
