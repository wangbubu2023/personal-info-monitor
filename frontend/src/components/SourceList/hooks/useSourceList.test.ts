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
    await act(async () => { vi.advanceTimersByTime(300) })
    expect(result.current.debouncedSearch).toBe('hello')
    vi.useRealTimers()
  })
})
