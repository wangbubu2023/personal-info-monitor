import api from './api'

export interface SourceStatusItem {
  id: string
  name: string
  type: string
  url: string
  enabled: boolean
  fetch_interval: number
  last_fetched_at: string | null
  next_fetch_at: string | null
  error_count: number
  last_error: string | null
  content_count: number
}

export interface QueueStatus {
  running_fetches: number
  running_processes: number
  fetch_concurrency: number
  sources_status: SourceStatusItem[]
}

export interface RuntimeFeatures {
  podcast_sources_enabled: boolean
  keyword_monitoring_enabled: boolean
  playwright_enabled: boolean
  x_playwright_enabled: boolean
  atoms_enabled: boolean
  atoms_relations_enabled: boolean
}

export const systemApi = {
  getQueueStatus: async (): Promise<QueueStatus> => {
    const response = await api.get<QueueStatus>('/system/queue')
    return response.data
  },

  getFeatures: async (): Promise<RuntimeFeatures> => {
    const response = await api.get<RuntimeFeatures>('/system/features')
    return response.data
  },
}
