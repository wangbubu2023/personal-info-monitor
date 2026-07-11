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
  event_items?: HourlyDigestEventItem[]
  items: DigestItem[]
  generated_at?: string
}

export interface HourlyDigestEventItem {
  event_key?: string | null
  event_id?: string | null
  section?: string | null
  content_id: string
  content_ids?: string[]
  title: string
  summary?: string | null
  what_happened?: string | null
  why_matters?: string | null
  new_signal?: string | null
  missing_confirmation?: string | null
  source_name: string
  source_names?: string[]
  source_keys?: string[]
  source_url?: string | null
  url: string
  local_reader_path?: string | null
  publish_time?: string | null
  fetched_at?: string | null
  score?: number | null
  importance_score?: number | null
  incremental_score?: number | null
  confidence_score?: number | null
  lane?: string | null
  duplicate_group_id?: string | null
  corroboration_tier?: string | null
  independent_source_count?: number | null
  is_repeat_event?: boolean
}

export interface TodayHighlightEvent {
  event_id: string
  event_key: string
  section?: string | null
  title: string
  summary?: string | null
  why_matters?: string | null
  what_changed?: string | null
  independent_source_count: number
  source_names: string[]
  updated_at?: string | null
  importance_score?: number | null
  confidence_score?: number | null
  primary_content_id?: string | null
}

export interface TodayHighlightsResponse {
  date: string
  items: TodayHighlightEvent[]
}

export interface EventTimelineItem {
  content_id: string
  title: string
  summary?: string | null
  source_name: string
  url: string
  publish_time?: string | null
  fetched_at?: string | null
  role: string
}

export interface EventSnapshotItem {
  version: number
  title: string
  summary?: string | null
  what_changed?: string | null
  why_matters?: string | null
  created_at?: string | null
}

export interface EventFeedbackItem {
  type: string
  note?: string | null
  created_at?: string | null
}

export interface EventEvidenceGroup {
  key: string
  title: string
  content_ids: string[]
}

export interface EventDetailResponse {
  event_id: string
  event_key: string
  title: string
  current_conclusion: string
  why_matters?: string | null
  source_names: string[]
  independent_source_count: number
  updated_at?: string | null
  timeline: EventTimelineItem[]
  snapshots: EventSnapshotItem[]
  primary_reports?: EventTimelineItem[]
  independent_verification?: EventEvidenceGroup[]
  related_discussions?: EventEvidenceGroup[]
  feedback: EventFeedbackItem[]
}

export interface EventFeedbackCreate {
  type: 'event_wrong_merge' | 'event_missing_merge'
  note?: string
  content_id?: string
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

  // Get 3-8 event highlights for the PIM Digest page.
  getTodayHighlights: async (date: string): Promise<TodayHighlightsResponse> => {
    const response = await api.get('/events/today-highlights', { params: { date } })
    return response.data
  },

  getEventDetail: async (eventId: string): Promise<EventDetailResponse> => {
    const response = await api.get(`/events/${eventId}`)
    return response.data
  },

  submitEventFeedback: async (eventId: string, body: EventFeedbackCreate): Promise<EventFeedbackItem> => {
    const response = await api.post(`/events/${eventId}/feedback`, body)
    return response.data
  },
}
