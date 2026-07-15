import api from './api'
import type { Source, SourceCreate, PaginatedResponse } from '../types'

const MAX_SOURCE_PAGE_SIZE = 200

export interface ListSourcesParams {
  page?: number
  page_size?: number
  type?: string
  enabled?: boolean
  search?: string
  sort_by?: 'name' | 'content_count'
  sort_order?: 'ascend' | 'descend' | 'asc' | 'desc'
}

/** Params for paginated source list (`listSources`). `scope` is client-only and not sent to the API. */
export interface SourceListParams {
  page?: number
  page_size?: number
  search?: string
  type?: string
  scope?: string
  sort_by?: 'name' | 'content_count'
  sort_order?: 'ascend' | 'descend' | 'asc' | 'desc'
}

export type PaginatedSourceResponse = PaginatedResponse<Source>

export interface PaidSourceMatrixItem {
  source_id: string
  source_name: string
  source_type: string
  host: string
  discovery: string
  body_path: string
  validation_url: string
  last_success_at?: string | null
  success_rate_7d?: number | null
  failure_code?: string | null
  recovery_action: string
  session_status?: string | null
  session_mode?: string | null
}

export interface PaidSourceMatrixResponse {
  items: PaidSourceMatrixItem[]
  total: number
  generated_at?: string | null
}

/**
 * Paginated source list. Prefer this or {@link sourcesApi.list} for UI; use {@link sourcesApi.listAll} only when the full catalog is required.
 */
export async function listSources(
  params: SourceListParams = {}
): Promise<PaginatedSourceResponse> {
  const { scope: _scope, ...rest } = params
  return sourcesApi.list(rest as ListSourcesParams)
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

  /**
   * Load every source by paging through the API. Avoid for main list UIs — use {@link sourcesApi.list} or {@link listSources}.
   * Still appropriate when a caller truly needs the full in-memory list (e.g. bulk workflows that enumerate all sources).
   */
  getPaidMatrix: async (): Promise<PaidSourceMatrixResponse> => {
    const response = await api.get('/sources/paid-matrix')
    return response.data
  },

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

  // Create source only persists config; probe is a separate action.
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
  bulkImport: async (
    sources: SourceCreate[],
  ): Promise<{ created: Source[]; skipped_duplicates: number }> => {
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
