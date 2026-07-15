import React from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useDashboard } from './useDashboard'
import { digestApi } from '../services/digest'

vi.mock('../services/digest', () => ({
  digestApi: {
    getDigest: vi.fn(async () => ({
      date: '2026-07-10',
      total_items: 0,
      categories: {
        websites: { count: 0, items: [] },
        rss: { count: 0, items: [] },
        x_accounts: { count: 0, items: [] },
        youtube: { count: 0, items: [] },
        podcasts: { count: 0, items: [] },
      },
    })),
    getDashboardStats: vi.fn(async () => ({
      today_total: 0,
      unread_count: 0,
      active_sources: 0,
      favorited_count: 0,
    })),
  },
}))

vi.mock('../services/sources', () => ({
  sourcesApi: {
    fetchAll: vi.fn(async () => ({ source_count: 0 })),
  },
}))

vi.mock('../services/contents', () => ({
  contentsApi: {
    list: vi.fn(async () => ({ items: [], total: 0 })),
  },
}))

vi.mock('../services/system', () => ({
  systemApi: {
    getQueueStatus: vi.fn(async () => ({ queued: 0, running: 0 })),
  },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('useDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads the complete date timeline without a read-state filter', async () => {
    const { result } = renderHook(() => useDashboard(), { wrapper })

    await waitFor(() => {
      expect(digestApi.getDigest).toHaveBeenCalled()
    })

    const params = vi.mocked(digestApi.getDigest).mock.calls[0][0]
    expect(params).not.toHaveProperty('unread_only')
    expect(result.current).not.toHaveProperty('viewMode')
  })
})
