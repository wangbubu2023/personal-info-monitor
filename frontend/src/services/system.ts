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
  atoms_reconcile_enabled?: boolean
  atoms_knowledge_enabled?: boolean
}

export interface UpgradeStatus {
  status: 'idle' | 'running' | 'succeeded' | 'failed'
  pid: number | null
  started_at: string | null
  finished_at: string | null
  exit_code: number | null
  command: string[]
  log_path: string
  log_tail: string
  message: string
  configured_args?: string[]
}

export interface UpdateCheckStatus {
  status: 'ok' | 'disabled' | 'error'
  current_version: string
  latest_version: string | null
  latest_tag: string | null
  update_available: boolean
  release_url: string | null
  published_at: string | null
  release_name: string | null
  release_notes: string
  checked_at: string
  message: string
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

  getUpgradeStatus: async (): Promise<UpgradeStatus> => {
    const response = await api.get<UpgradeStatus>('/system/upgrade')
    return response.data
  },

  checkForUpdates: async (): Promise<UpdateCheckStatus> => {
    const response = await api.get<UpdateCheckStatus>('/system/update-check')
    return response.data
  },

  startUpgrade: async (): Promise<UpgradeStatus> => {
    const response = await api.post<UpgradeStatus>('/system/upgrade')
    return response.data
  },

  downloadSupportBundle: async (): Promise<void> => {
    const response = await api.get<Blob>('/system/support-bundle', {
      responseType: 'blob',
    })
    const disposition = response.headers['content-disposition'] || ''
    const filenameMatch = disposition.match(/filename="([^"]+)"/)
    const filename = filenameMatch?.[1] || `pim-support-bundle-${Date.now()}.zip`
    const blobUrl = URL.createObjectURL(response.data)
    const link = document.createElement('a')
    link.href = blobUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(blobUrl)
  },
}
