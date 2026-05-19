import api from './api'
import type {
  Keyword,
  KeywordBatchCreate,
  KeywordBatchCreateResponse,
  KeywordBatchUpdate,
  KeywordBatchUpdateResponse,
  KeywordCreate,
} from '../types'

export const keywordsApi = {
  // List keywords
  list: async (enabled?: boolean): Promise<{ items: Keyword[]; total: number }> => {
    const response = await api.get('/keywords', { params: { enabled } })
    return response.data
  },

  // Get single keyword
  get: async (id: string): Promise<Keyword> => {
    const response = await api.get(`/keywords/${id}`)
    return response.data
  },

  // Create keyword
  create: async (data: KeywordCreate): Promise<Keyword> => {
    const response = await api.post('/keywords', data)
    return response.data
  },

  // Batch create keywords
  createBatch: async (data: KeywordBatchCreate): Promise<KeywordBatchCreateResponse> => {
    const response = await api.post('/keywords/batch', data)
    return response.data
  },

  // Batch update keywords
  updateBatch: async (data: KeywordBatchUpdate): Promise<KeywordBatchUpdateResponse> => {
    const response = await api.patch('/keywords/batch', data)
    return response.data
  },

  // Update keyword
  update: async (id: string, data: Partial<KeywordCreate>): Promise<Keyword> => {
    const response = await api.patch(`/keywords/${id}`, data)
    return response.data
  },

  // Delete keyword
  delete: async (id: string): Promise<void> => {
    await api.delete(`/keywords/${id}`)
  },
}
