import api from './api'
import type {
  AtomListParams,
  AtomListResponse,
  AtomRecord,
  AtomStatsResponse,
  AtomUpdatePayload,
  RelationCreatePayload,
  RelationListResponse,
  RelationRecord,
} from '../types/atoms'

export const atomsApi = {
  list: async (params: AtomListParams = {}): Promise<AtomListResponse> => {
    const response = await api.get<AtomListResponse>('/atoms', { params })
    return response.data
  },

  get: async (atomId: string): Promise<AtomRecord> => {
    const response = await api.get<AtomRecord>(`/atoms/${atomId}`)
    return response.data
  },

  stats: async (): Promise<AtomStatsResponse> => {
    const response = await api.get<AtomStatsResponse>('/atoms/stats')
    return response.data
  },

  update: async (atomId: string, body: AtomUpdatePayload): Promise<AtomRecord> => {
    const response = await api.patch<AtomRecord>(`/atoms/${atomId}`, body)
    return response.data
  },

  verify: async (atomId: string): Promise<AtomRecord> => {
    const response = await api.post<AtomRecord>(`/atoms/${atomId}/verify`)
    return response.data
  },

  atomizeContent: async (contentId: string): Promise<{ content_id: string; ok: boolean }> => {
    const response = await api.post<{ content_id: string; ok: boolean }>(
      `/atoms/content/${contentId}/atomize`,
    )
    return response.data
  },

  listRelations: async (atomId: string): Promise<RelationListResponse> => {
    const response = await api.get<RelationListResponse>(`/atoms/${atomId}/relations`)
    return response.data
  },

  createRelation: async (body: RelationCreatePayload): Promise<RelationRecord> => {
    const response = await api.post<RelationRecord>('/atom-relations', body)
    return response.data
  },

  verifyRelation: async (relId: string): Promise<RelationRecord> => {
    const response = await api.post<RelationRecord>(`/atom-relations/${relId}/verify`)
    return response.data
  },

  deleteRelation: async (relId: string): Promise<void> => {
    await api.delete(`/atom-relations/${relId}`)
  },
}
