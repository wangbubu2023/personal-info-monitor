import api from './api'

export type ScoreFeedbackDirection = 'too_high' | 'too_low' | 'ok'
export type ScoreFeedbackEventType = 'score_calibration' | 'open' | 'star' | 'hide'
export type ScoreSelectionStatus = 'selected' | 'candidate' | 'rejected'

export interface ScoreLabContentSummary {
  id: string
  title: string
  source_name?: string | null
  content_type: string
  original_url: string
  publish_time?: string | null
  fetched_at?: string | null
  article_score?: number | null
  selection_status?: string | null
  lane?: string | null
  lane_label?: string | null
  fetch_acceptance?: string | null
}

export interface ScoreLaneDefinition {
  value: string
  label_zh: string
  label_en: string
  description: string
}

export interface ScoreLabContentListResponse {
  items: ScoreLabContentSummary[]
  total: number
  page: number
  page_size: number
}

export interface WeightBreakdownRow {
  dimension: string
  label: string
  weight: number
  score: number
  weighted: number
}

export interface ScoreExplainPayload {
  score_version: string
  lane: string
  lane_label: string
  lane_scores: Record<string, number>
  scoring_title: string
  corpus: { headline: string; depth_prefix: string }
  impact_cap_scope?: string | null
  impact_caps_applied: Record<string, number>
  matched_signals: {
    commerce: string[]
    narrow: string[]
    market_offering_exempt: string[]
  }
  entity_hits: Array<{ term: string; tier: string; score: number; user_keyword?: boolean }>
  event_pattern_hits: Array<{ pattern: string; bonus: number; matched: string[] }>
  reach_level: string
  user_keywords: { configured: string[]; matched: string[]; salience_bonus?: number }
  dimension_scores_before_cap: Record<string, number>
  dimension_scores: Record<string, number>
  weight_breakdown: WeightBreakdownRow[]
  weighted_sum_0_10: number
  thresholds: {
    selected: number
    candidate: number
    minimum_selected_confidence: number
  }
  recomputed: {
    article_score: number
    final_score: number
    selection_status: string
    score_confidence?: number
    recommendation_reason?: Record<string, unknown>
  }
  stored: Record<string, unknown>
  score_delta?: number | null
  fetch_acceptance?: string | null
  fulltext_status?: string | null
  content?: {
    id: string
    title: string
    summary?: string | null
    original_url: string
    content_type: string
    source_name?: string | null
  }
}

export interface ScoreFeedbackItem {
  id: string
  content_id: string
  direction: ScoreFeedbackDirection | 'open' | 'star' | 'hide'
  expected_status?: string | null
  note?: string | null
  event_type?: ScoreFeedbackEventType | null
  event_value?: unknown
  snapshot: Record<string, unknown>
  created_at: string
  content_title?: string | null
}

export interface ListScoreLabContentsParams {
  page?: number
  page_size?: number
  selection_status?: string
  lane?: string
  min_score?: number
  max_score?: number
  search?: string
}

export const scoreLabApi = {
  listLanes: async (): Promise<ScoreLaneDefinition[]> => {
    const { data } = await api.get<{ items: ScoreLaneDefinition[] }>('/score-lab/lanes')
    return data.items
  },

  listContents: async (params: ListScoreLabContentsParams = {}): Promise<ScoreLabContentListResponse> => {
    const { data } = await api.get<ScoreLabContentListResponse>('/score-lab/contents', { params })
    return data
  },

  explain: async (contentId: string): Promise<ScoreExplainPayload> => {
    const { data } = await api.get<{ explain: ScoreExplainPayload }>(`/score-lab/contents/${contentId}/explain`)
    return data.explain
  },

  submitFeedback: async (payload: {
    content_id: string
    direction: ScoreFeedbackDirection
    expected_status?: ScoreSelectionStatus
    note?: string
  }): Promise<ScoreFeedbackItem> => {
    const { data } = await api.post<ScoreFeedbackItem>('/score-lab/feedback', payload)
    return data
  },

  listFeedback: async (limit = 50): Promise<{ items: ScoreFeedbackItem[]; total: number }> => {
    const { data } = await api.get<{ items: ScoreFeedbackItem[]; total: number }>('/score-lab/feedback', {
      params: { limit },
    })
    return data
  },
}
