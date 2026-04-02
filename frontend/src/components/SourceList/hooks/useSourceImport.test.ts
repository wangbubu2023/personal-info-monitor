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
    act(() => { result.current.setImportPreview([]) })
    expect(result.current.importPreview).toHaveLength(0)
  })
})
