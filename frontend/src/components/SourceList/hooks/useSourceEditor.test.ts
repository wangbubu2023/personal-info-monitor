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

  it('binds an active browser session through source metadata', async () => {
    const { sourcesApi } = await import('../../../services/sources')
    const browserSession = {
      id: 'session-wsj',
      site_url: 'https://www.wsj.com/',
      site_host: 'wsj.com',
      profile_name: 'wsj',
      session_mode: 'persistent_profile',
      status: 'active',
      metadata_: {},
    } as any
    const { result } = renderHook(
      () => useSourceEditor({
        authConfigs: [],
        browserSessions: [browserSession],
        sourceLimitReached: false,
        maxSources: 200,
        defaultSharedXAuthConfigId: undefined,
      }),
      { wrapper },
    )

    await act(async () => {
      await result.current.handleSubmit({
        name: 'WSJ',
        type: 'website',
        url: 'https://www.wsj.com/',
        enabled: true,
        fetch_interval: 60,
        use_keyword_filter: false,
        auth_required: false,
        paywall_enabled: true,
        website_auth_config_id: 'browser-session:session-wsj',
      } as any)
    })

    const payload = (sourcesApi.create as any).mock.calls[0][0]
    expect(payload.auth_required).toBe(true)
    expect(payload.auth_config_id).toBeNull()
    expect(payload.metadata.browser_session_id).toBe('session-wsj')
  })

  it('hydrates a linked browser session into the website credential field', () => {
    const browserSession = {
      id: 'session-wsj',
      site_url: 'https://www.wsj.com/',
      site_host: 'wsj.com',
      profile_name: 'wsj',
      session_mode: 'persistent_profile',
      status: 'active',
      metadata_: {},
    } as any
    const { result } = renderHook(
      () => useSourceEditor({
        authConfigs: [],
        browserSessions: [browserSession],
        sourceLimitReached: false,
        maxSources: 200,
        defaultSharedXAuthConfigId: undefined,
      }),
      { wrapper },
    )

    act(() => {
      result.current.handleEdit({
        id: 'src-wsj',
        name: 'WSJ',
        type: 'website',
        url: 'https://www.wsj.com/',
        enabled: true,
        fetch_interval: 60,
        use_keyword_filter: false,
        auth_required: true,
        auth_config_id: null,
        extra_urls: [],
        metadata: { browser_session_id: 'session-wsj' },
      } as any)
    })

    expect(result.current.form.getFieldValue('paywall_enabled')).toBe(true)
    expect(result.current.form.getFieldValue('website_auth_config_id')).toBe(
      'browser-session:session-wsj',
    )
  })

  it('clears a persisted browser session binding when website credentials are disabled', async () => {
    const { sourcesApi } = await import('../../../services/sources')
    const { result } = renderHook(
      () => useSourceEditor({
        authConfigs: [],
        sourceLimitReached: false,
        maxSources: 200,
        defaultSharedXAuthConfigId: undefined,
      }),
      { wrapper },
    )

    act(() => {
      result.current.handleEdit({
        id: 'src-wsj',
        name: 'WSJ',
        type: 'website',
        url: 'https://www.wsj.com/',
        enabled: true,
        fetch_interval: 60,
        use_keyword_filter: false,
        auth_required: true,
        auth_config_id: null,
        extra_urls: [],
        metadata: { browser_session_id: 'session-wsj' },
      } as any)
    })

    await act(async () => {
      await result.current.handleSubmit({
        name: 'WSJ',
        type: 'website',
        url: 'https://www.wsj.com/',
        enabled: true,
        fetch_interval: 60,
        use_keyword_filter: false,
        auth_required: true,
        paywall_enabled: false,
        metadata: { browser_session_id: 'session-wsj' },
      } as any)
    })

    const payload = (sourcesApi.update as any).mock.calls[0][1]
    expect(payload.auth_required).toBe(false)
    expect(payload.auth_config_id).toBeNull()
    expect(payload.metadata.browser_session_id).toBeNull()
  })

  it('forces website sources into automatic fetch strategy mode', async () => {
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
        metadata: {
          rss_only: true,
          bpc_spoof_ua: 'googlebot',
          bpc_spoof_referer: 'google',
          bpc_random_ip: true,
          bpc_block_paywalls: true,
          bpc_ephemeral_context: true,
        },
      } as any)
    })
    expect(sourcesApi.create).toHaveBeenCalledTimes(1)
    const payload = (sourcesApi.create as any).mock.calls[0][0]
    expect(payload.metadata.fetch_strategy_mode).toBe('auto')
    expect(payload.metadata).not.toHaveProperty('rss_only')
    expect(payload.metadata).not.toHaveProperty('bpc_spoof_ua')
    expect(payload.metadata).not.toHaveProperty('bpc_spoof_referer')
    expect(payload.metadata).not.toHaveProperty('bpc_random_ip')
    expect(payload.metadata).not.toHaveProperty('bpc_block_paywalls')
    expect(payload.metadata).not.toHaveProperty('bpc_ephemeral_context')
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

  it('strips website strategy metadata for non-website source types', async () => {
    const { sourcesApi } = await import('../../../services/sources')
    const { result } = renderHook(
      () => useSourceEditor({ authConfigs: [], sourceLimitReached: false, maxSources: 200, defaultSharedXAuthConfigId: undefined }),
      { wrapper },
    )
    await act(async () => {
      await result.current.handleSubmit({
        name: 'Some RSS',
        type: 'rss',
        url: 'https://example.com/feed',
        enabled: true,
        fetch_interval: 60,
        use_keyword_filter: false,
        auth_required: false,
        metadata: {
          rss_only: true,
          fetch_strategy_mode: 'auto',
          bpc_spoof_ua: 'googlebot',
          bpc_block_paywalls: true,
        },
      } as any)
    })
    const payload = (sourcesApi.create as any).mock.calls[0][0]
    expect(payload.metadata).not.toHaveProperty('rss_only')
    expect(payload.metadata).not.toHaveProperty('fetch_strategy_mode')
    expect(payload.metadata).not.toHaveProperty('bpc_spoof_ua')
    expect(payload.metadata).not.toHaveProperty('bpc_block_paywalls')
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

})
