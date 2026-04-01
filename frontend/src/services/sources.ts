import api from './api'
import type { Source, SourceCreate, PaginatedResponse } from '../types'

const MAX_SOURCE_PAGE_SIZE = 200

export interface ListSourcesParams {
  page?: number
  page_size?: number
  type?: string
  category_id?: string
  enabled?: boolean
  search?: string
}

export interface ProbeResult {
  status: 'ok' | 'warning' | 'error' | 'unknown'
  strategy: string
  rss_url?: string
  message: string
  sample_count: number
}

export const sourcesApi = {
  // List sources
  list: async (params?: ListSourcesParams): Promise<PaginatedResponse<Source>> => {
    const response = await api.get('/sources', {
      params: {
        ...params,
        page_size: params?.page_size ? Math.min(params.page_size, MAX_SOURCE_PAGE_SIZE) : params?.page_size,
      },
    })
    return response.data
  },

  // Load the full source library across multiple backend pages
  listAll: async (params?: Omit<ListSourcesParams, 'page' | 'page_size'>): Promise<Source[]> => {
    const items: Source[] = []
    let page = 1
    let totalPages = 1

    while (page <= totalPages) {
      const response = await sourcesApi.list({
        ...params,
        page,
        page_size: MAX_SOURCE_PAGE_SIZE,
      })
      items.push(...response.items)
      totalPages = Math.max(1, response.total_pages || 1)
      page += 1
    }

    return items
  },

  // Get single source
  get: async (id: string): Promise<Source> => {
    const response = await api.get(`/sources/${id}`)
    return response.data
  },

  // Create source
  create: async (data: SourceCreate): Promise<Source> => {
    const response = await api.post('/sources', data)
    return response.data
  },

  // Update source
  update: async (id: string, data: Partial<SourceCreate>): Promise<Source> => {
    const response = await api.patch(`/sources/${id}`, data)
    return response.data
  },

  // Delete source
  delete: async (id: string): Promise<void> => {
    await api.delete(`/sources/${id}`)
  },

  // Bulk import (with longer timeout for large imports)
  bulkImport: async (sources: SourceCreate[]): Promise<Source[]> => {
    const response = await api.post('/sources/bulk-import', { sources }, {
      timeout: 300000  // 5 minutes for large imports
    })
    return response.data
  },

  // Export
  export: async (): Promise<{ sources: Source[]; exported_at: string }> => {
    const response = await api.get('/sources/export')
    return response.data
  },

  // Trigger fetch for single source
  triggerFetch: async (id: string): Promise<{ message: string; task_id: string }> => {
    const response = await api.post(`/sources/${id}/fetch`)
    return response.data
  },

  // Trigger fetch for all sources
  fetchAll: async (): Promise<{ message: string; task_id: string; source_count: number }> => {
    const response = await api.post('/sources/fetch-all')
    return response.data
  },

  // Probe a URL (without creating a source)
  probeUrl: async (url: string, type: string = 'website'): Promise<ProbeResult> => {
    const response = await api.post('/sources/probe', { url, type })
    return response.data
  },

  // Re-probe an existing source
  probeSource: async (id: string): Promise<Source> => {
    const response = await api.post(`/sources/${id}/probe`)
    return response.data
  },

  // Probe all enabled sources
  probeAll: async (): Promise<{ message: string; total: number }> => {
    const response = await api.post('/sources/probe-all', {}, {
      timeout: 300000  // 5 minutes for probing all sources
    })
    return response.data
  },
}
