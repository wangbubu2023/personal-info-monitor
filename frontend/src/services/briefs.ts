import api from './api'

export interface BriefSummary {
  brief_id: string
  period_key: string
  brief_type: string
  version: number
  title: string
  summary_content: string
  lineage_snapshot: Record<string, unknown>
  modality_status: string
  publication_status: string
  modality_violation_count: number
  created_at?: string | null
}

export const briefsApi = {
  list: async (params?: { brief_type?: string; period_key?: string }): Promise<{ items: BriefSummary[] }> => {
    const response = await api.get('/briefs', { params })
    return response.data
  },
  generate: async (payload: { period_key: string; brief_type: string; topic_id?: string; regenerate?: boolean }) => {
    const response = await api.post('/briefs/generate', payload)
    return response.data as BriefSummary
  },
}
