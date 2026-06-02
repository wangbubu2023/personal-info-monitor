import api from './api'
import type { Digest, DigestItem, DashboardStats } from '../types'

export interface DigestParams {
  date?: string
  date_from?: string
  date_to?: string
  sort?: 'time_desc' | 'score_desc'
  keyword_ids?: string[]
  unread_only?: boolean
  source_types?: string[]
}

export interface DigestStats {
  period: {
    start: string
    end: string
    days: number
  }
  daily_counts: Array<{ date: string; count: number }>
  type_counts: Record<string, number>
  unread_count: number
  favorited_count: number
}

export interface HourlyDigestSummary {
  hour: number
  title?: string
  content_count: number
  summary?: string
  generated_at?: string
  sources: {
    websites: number
    x: number
    youtube: number
    podcasts: number
  }
}

export interface HourlyDigestDetail {
  hour: number
  date: string
  title?: string
  summary?: string
  content_count: number
  sources: string[]
  items: DigestItem[]
  generated_at?: string
}

export const digestApi = {
  // Get daily digest
  getDigest: async (params?: DigestParams): Promise<Digest> => {
    const response = await api.get('/digest', { params })
    return response.data
  },

  // Get digest stats
  getStats: async (days?: number): Promise<DigestStats> => {
    const response = await api.get('/digest/stats', { params: { days } })
    return response.data
  },

  // Get dashboard stats
  getDashboardStats: async (): Promise<DashboardStats> => {
    const response = await api.get('/dashboard/stats')
    return response.data
  },

  // Get hourly digest list for a date
  getHourlyDigests: async (date: string): Promise<HourlyDigestSummary[]> => {
    const response = await api.get('/digest/hourly', { params: { date } })
    return response.data
  },

  // Get hourly digest detail for a specific hour
  getHourlyDigestDetail: async (hour: number, date: string): Promise<HourlyDigestDetail> => {
    const response = await api.get(`/digest/hourly/${hour}`, { params: { date } })
    return response.data
  },
}
