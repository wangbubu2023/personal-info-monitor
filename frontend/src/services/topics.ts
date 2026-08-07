import api from './api'

export interface TopicSummary {
  topic_id: string
  title: string
  description?: string | null
  creation_type: string
  rule_spec?: Record<string, unknown>
  status: string
  event_count: number
  unique_source_count: number
  source_coverage: string[]
  timeline?: Array<{ event_id: string; title: string; summary?: string | null }>
  created_at?: string | null
}

export const topicsApi = {
  list: async (params?: { status?: string; creation_type?: string; query?: string }): Promise<{ items: TopicSummary[] }> => {
    const response = await api.get('/topics', { params })
    return response.data
  },
  create: async (payload: { title: string; description?: string; creation_type?: string; rule_spec?: Record<string, unknown> }) => {
    const response = await api.post('/topics', payload)
    return response.data
  },
  archive: async (topicId: string) => {
    const response = await api.delete(`/topics/${topicId}`)
    return response.data
  },
}
