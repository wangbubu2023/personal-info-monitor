import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
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
}))

import { useSourceEditor } from './useSourceEditor'

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return React.createElement(QueryClientProvider, { client: qc }, children)
}

describe('useSourceEditor', () => {
  beforeEach(() => vi.clearAllMocks())

  it('initialises with isModalOpen=false and editingSource=null', () => {
    const { result } = renderHook(() => useSourceEditor({ authConfigs: [], sourceLimitReached: false, maxSources: 200, defaultSharedXAuthConfigId: undefined }), { wrapper })
    expect(result.current.isModalOpen).toBe(false)
    expect(result.current.editingSource).toBeNull()
  })

  it('handleAdd opens modal and resets editingSource', () => {
    const { result } = renderHook(() => useSourceEditor({ authConfigs: [], sourceLimitReached: false, maxSources: 200, defaultSharedXAuthConfigId: undefined }), { wrapper })
    act(() => { result.current.handleAdd() })
    expect(result.current.isModalOpen).toBe(true)
    expect(result.current.editingSource).toBeNull()
  })

  it('handleAdd does not open modal when sourceLimitReached=true', () => {
    const { result } = renderHook(() => useSourceEditor({ authConfigs: [], sourceLimitReached: true, maxSources: 200, defaultSharedXAuthConfigId: undefined }), { wrapper })
    act(() => { result.current.handleAdd() })
    expect(result.current.isModalOpen).toBe(false)
  })

  it('matchAuthConfigByHost returns undefined for empty configs', () => {
    const { result } = renderHook(() => useSourceEditor({ authConfigs: [], sourceLimitReached: false, maxSources: 200, defaultSharedXAuthConfigId: undefined }), { wrapper })
    expect(result.current.matchAuthConfigByHost('https://example.com', [])).toBeUndefined()
  })

  // ---------------------------------------------------------------------
  // rss_only metadata toggle
  //
  // These tests verify the "仅 RSS 摘要" switch round-trips correctly
  // through metadata.rss_only so operators can disable Playwright
  // hydration for DataDome-walled sites without losing the config.
  // ---------------------------------------------------------------------
  it('writes metadata.rss_only=true when rss_only_enabled is on (create)', async () => {
    const { sourcesApi } = await import('../../../services/sources')
    const { result } = renderHook(
      () => useSourceEditor({ authConfigs: [], sourceLimitReached: false, maxSources: 200, defaultSharedXAuthConfigId: undefined }),
      { wrapper },
    )
    await act(async () => {
      await result.current.handleSubmit({
        name: 'NYT',
        type: 'website',
        url: 'https://www.nytimes.com',
        enabled: true,
        fetch_interval: 60,
        use_keyword_filter: false,
        auth_required: false,
        paywall_enabled: false,
        rss_only_enabled: true,
      } as any)
    })
    expect(sourcesApi.create).toHaveBeenCalledTimes(1)
    const payload = (sourcesApi.create as any).mock.calls[0][0]
    expect(payload.metadata).toMatchObject({ rss_only: true })
  })

  it('writes source quality metadata from editor fields', async () => {
    const { sourcesApi } = await import('../../../services/sources')
    const { result } = renderHook(
      () => useSourceEditor({ authConfigs: [], sourceLimitReached: false, maxSources: 200, defaultSharedXAuthConfigId: undefined }),
      { wrapper },
    )
    await act(async () => {
      await result.current.handleSubmit({
        name: 'OpenAI Blog',
        type: 'rss',
        url: 'https://openai.com/news/rss.xml',
        enabled: true,
        fetch_interval: 60,
        use_keyword_filter: false,
        auth_required: false,
        source_stars: 3,
        authority_type: 'official',
        source_weight: 1.2,
      } as any)
    })

    const payload = (sourcesApi.create as any).mock.calls[0][0]
    expect(payload.metadata).toMatchObject({
      source_stars: 3,
      source_weight: 1.2,
    })
    expect(payload.metadata).not.toHaveProperty('authority_type')
    expect(payload.metadata).not.toHaveProperty('domain_focus')
  })

  it('omits metadata.rss_only when toggle is off on new source', async () => {
    const { sourcesApi } = await import('../../../services/sources')
    const { result } = renderHook(
      () => useSourceEditor({ authConfigs: [], sourceLimitReached: false, maxSources: 200, defaultSharedXAuthConfigId: undefined }),
      { wrapper },
    )
    await act(async () => {
      await result.current.handleSubmit({
        name: 'Plain',
        type: 'website',
        url: 'https://example.com',
        enabled: true,
        fetch_interval: 60,
        use_keyword_filter: false,
        auth_required: false,
        paywall_enabled: false,
        rss_only_enabled: false,
      } as any)
    })
    const payload = (sourcesApi.create as any).mock.calls[0][0]
    expect(payload.metadata).not.toHaveProperty('rss_only')
  })

  it('strips metadata.rss_only for non-website source types', async () => {
    const { sourcesApi } = await import('../../../services/sources')
    const { result } = renderHook(
      () => useSourceEditor({ authConfigs: [], sourceLimitReached: false, maxSources: 200, defaultSharedXAuthConfigId: undefined }),
      { wrapper },
    )
    await act(async () => {
      // Even if the form value somehow leaks onto an rss source (e.g. user
      // switched types after flipping the toggle), metadata stays clean.
      await result.current.handleSubmit({
        name: 'Some RSS',
        type: 'rss',
        url: 'https://example.com/feed',
        enabled: true,
        fetch_interval: 60,
        use_keyword_filter: false,
        auth_required: false,
        rss_only_enabled: true,
      } as any)
    })
    const payload = (sourcesApi.create as any).mock.calls[0][0]
    expect(payload.metadata).not.toHaveProperty('rss_only')
  })

  it('writes BPC metadata for website sources', async () => {
    const { sourcesApi } = await import('../../../services/sources')
    const { result } = renderHook(
      () => useSourceEditor({ authConfigs: [], sourceLimitReached: false, maxSources: 200, defaultSharedXAuthConfigId: undefined }),
      { wrapper },
    )
    await act(async () => {
      await result.current.handleSubmit({
        name: 'Strict Site',
        type: 'website',
        url: 'https://example.com',
        enabled: true,
        fetch_interval: 60,
        use_keyword_filter: false,
        auth_required: false,
        paywall_enabled: false,
        bpc_spoof_ua: 'googlebot',
        bpc_spoof_referer: 'google',
        bpc_random_ip: true,
        bpc_block_paywalls: true,
        bpc_ephemeral_context: true,
      } as any)
    })

    const payload = (sourcesApi.create as any).mock.calls[0][0]
    expect(payload.metadata).toMatchObject({
      bpc_spoof_ua: 'googlebot',
      bpc_spoof_referer: 'google',
      bpc_random_ip: true,
      bpc_block_paywalls: true,
      bpc_ephemeral_context: true,
    })
  })

  it('strips BPC metadata for non-website source types', async () => {
    const { sourcesApi } = await import('../../../services/sources')
    const { result } = renderHook(
      () => useSourceEditor({ authConfigs: [], sourceLimitReached: false, maxSources: 200, defaultSharedXAuthConfigId: undefined }),
      { wrapper },
    )
    await act(async () => {
      await result.current.handleSubmit({
        name: 'RSS',
        type: 'rss',
        url: 'https://example.com/feed.xml',
        enabled: true,
        fetch_interval: 60,
        use_keyword_filter: false,
        auth_required: false,
        metadata: {
          bpc_spoof_ua: 'googlebot',
          bpc_block_paywalls: true,
        },
        bpc_spoof_ua: 'bingbot',
        bpc_spoof_referer: 'twitter',
        bpc_random_ip: true,
        bpc_block_paywalls: true,
        bpc_ephemeral_context: true,
      } as any)
    })

    const payload = (sourcesApi.create as any).mock.calls[0][0]
    expect(payload.metadata).not.toHaveProperty('bpc_spoof_ua')
    expect(payload.metadata).not.toHaveProperty('bpc_spoof_referer')
    expect(payload.metadata).not.toHaveProperty('bpc_random_ip')
    expect(payload.metadata).not.toHaveProperty('bpc_block_paywalls')
    expect(payload.metadata).not.toHaveProperty('bpc_ephemeral_context')
  })

  it('rejects BPC ephemeral mode when website credentials are enabled', async () => {
    const { sourcesApi } = await import('../../../services/sources')
    const { result } = renderHook(
      () => useSourceEditor({ authConfigs: [], sourceLimitReached: false, maxSources: 200, defaultSharedXAuthConfigId: undefined }),
      { wrapper },
    )
    await act(async () => {
      await result.current.handleSubmit({
        name: 'Credential Site',
        type: 'website',
        url: 'https://example.com',
        enabled: true,
        fetch_interval: 60,
        use_keyword_filter: false,
        auth_required: false,
        paywall_enabled: true,
        bpc_ephemeral_context: true,
      } as any)
    })

    expect(sourcesApi.create).not.toHaveBeenCalled()
    expect(result.current.submitError).toContain('强制无痕模式不能与登录凭据复用同时开启')
  })

  it('clears BPC form fields when switching a new source to X', () => {
    const { result } = renderHook(
      () => useSourceEditor({ authConfigs: [], sourceLimitReached: false, maxSources: 200, defaultSharedXAuthConfigId: undefined }),
      { wrapper },
    )
    act(() => {
      result.current.handleAdd()
      result.current.form.setFieldsValue({
        bpc_spoof_ua: 'googlebot',
        bpc_spoof_referer: 'google',
        bpc_random_ip: true,
        bpc_block_paywalls: true,
        bpc_ephemeral_context: true,
      })
      result.current.handleTypeChange('x')
    })

    expect(result.current.form.getFieldValue('bpc_spoof_ua')).toBeUndefined()
    expect(result.current.form.getFieldValue('bpc_spoof_referer')).toBeUndefined()
    expect(result.current.form.getFieldValue('bpc_random_ip')).toBe(false)
    expect(result.current.form.getFieldValue('bpc_block_paywalls')).toBe(false)
    expect(result.current.form.getFieldValue('bpc_ephemeral_context')).toBe(false)
  })

  it('handleEdit hydrates rss_only_enabled from metadata.rss_only', () => {
    const { result } = renderHook(
      () => useSourceEditor({ authConfigs: [], sourceLimitReached: false, maxSources: 200, defaultSharedXAuthConfigId: undefined }),
      { wrapper },
    )
    act(() => {
      result.current.handleEdit({
        id: 'src-1',
        name: 'NYT',
        type: 'website',
        url: 'https://www.nytimes.com',
        enabled: true,
        fetch_interval: 60,
        use_keyword_filter: false,
        auth_required: false,
        auth_config_id: null,
        extra_urls: [],
        metadata: { rss_only: true },
      } as any)
    })
    expect(result.current.form.getFieldValue('rss_only_enabled')).toBe(true)
  })

  it('handleEdit hydrates source quality fields from metadata', () => {
    const { result } = renderHook(
      () => useSourceEditor({ authConfigs: [], sourceLimitReached: false, maxSources: 200, defaultSharedXAuthConfigId: undefined }),
      { wrapper },
    )
    act(() => {
      result.current.handleEdit({
        id: 'src-quality',
        name: 'OpenAI Blog',
        type: 'rss',
        url: 'https://openai.com/news/rss.xml',
        enabled: true,
        fetch_interval: 60,
        use_keyword_filter: false,
        auth_required: false,
        auth_config_id: null,
        extra_urls: [],
        metadata: {
          source_stars: 3,
          authority_type: 'official_blog',
          source_weight: 1.2,
        },
      } as any)
    })

    expect(result.current.form.getFieldValue('source_stars')).toBe(3)
    expect(result.current.form.getFieldValue('authority_type')).toBeUndefined()
    expect(result.current.form.getFieldValue('domain_focus_text')).toBeUndefined()
    expect(result.current.form.getFieldValue('source_weight')).toBe(1.2)
  })

  it('preserves hidden legacy metadata when editing a source', async () => {
    const { sourcesApi } = await import('../../../services/sources')
    const { result } = renderHook(
      () => useSourceEditor({ authConfigs: [], sourceLimitReached: false, maxSources: 200, defaultSharedXAuthConfigId: undefined }),
      { wrapper },
    )
    act(() => {
      result.current.handleEdit({
        id: 'src-legacy',
        name: 'Legacy',
        type: 'rss',
        url: 'https://example.com/feed.xml',
        enabled: true,
        fetch_interval: 60,
        use_keyword_filter: false,
        auth_required: false,
        auth_config_id: null,
        extra_urls: [],
        metadata: {
          source_stars: 2,
          authority_type: 'official',
          max_fetch_lag_minutes: 120,
        },
      } as any)
    })
    await waitFor(() => expect(result.current.editingSource?.id).toBe('src-legacy'))

    await act(async () => {
      await result.current.handleSubmit({
        name: 'Legacy',
        type: 'rss',
        url: 'https://example.com/feed.xml',
        enabled: true,
        fetch_interval: 60,
        use_keyword_filter: false,
        auth_required: false,
        metadata: {
          source_stars: 2,
          authority_type: 'official',
          max_fetch_lag_minutes: 120,
        },
        source_stars: 2,
        source_weight: 1,
      } as any)
    })

    const payload = (sourcesApi.update as any).mock.calls[0][1]
    expect(payload.metadata.authority_type).toBe('official')
    expect(payload.metadata.max_fetch_lag_minutes).toBe(120)
  })

  it('handleEdit defaults rss_only_enabled to false when metadata is silent', () => {
    const { result } = renderHook(
      () => useSourceEditor({ authConfigs: [], sourceLimitReached: false, maxSources: 200, defaultSharedXAuthConfigId: undefined }),
      { wrapper },
    )
    act(() => {
      result.current.handleEdit({
        id: 'src-2',
        name: 'Generic',
        type: 'website',
        url: 'https://example.com',
        enabled: true,
        fetch_interval: 60,
        use_keyword_filter: false,
        auth_required: false,
        auth_config_id: null,
        extra_urls: [],
        metadata: {},
      } as any)
    })
    expect(result.current.form.getFieldValue('rss_only_enabled')).toBe(false)
  })

  it('handleEdit hydrates BPC metadata fields', () => {
    const { result } = renderHook(
      () => useSourceEditor({ authConfigs: [], sourceLimitReached: false, maxSources: 200, defaultSharedXAuthConfigId: undefined }),
      { wrapper },
    )
    act(() => {
      result.current.handleEdit({
        id: 'src-bpc',
        name: 'Strict Site',
        type: 'website',
        url: 'https://example.com',
        enabled: true,
        fetch_interval: 60,
        use_keyword_filter: false,
        auth_required: false,
        auth_config_id: null,
        extra_urls: [],
        metadata: {
          bpc_spoof_ua: 'googlebot',
          bpc_spoof_referer: 'google',
          bpc_random_ip: true,
          bpc_block_paywalls: true,
          bpc_ephemeral_context: true,
        },
      } as any)
    })

    expect(result.current.form.getFieldValue('bpc_spoof_ua')).toBe('googlebot')
    expect(result.current.form.getFieldValue('bpc_spoof_referer')).toBe('google')
    expect(result.current.form.getFieldValue('bpc_random_ip')).toBe(true)
    expect(result.current.form.getFieldValue('bpc_block_paywalls')).toBe(true)
    expect(result.current.form.getFieldValue('bpc_ephemeral_context')).toBe(true)
  })
})
