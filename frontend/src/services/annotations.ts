import api from './api'

export type AnnotationTargetType = 'content' | 'event' | 'atom' | 'event_pair' | 'atom_relation'

export interface AnnotationLabelItem {
  id: string
  task_id: string
  task_type: string
  target_type: string
  target_id: string
  label_payload: { value?: string; [key: string]: unknown }
  note?: string | null
  confidence?: number | null
  annotator: string
  supersedes_id?: string | null
  task_status: string
  created_at?: string | null
}

export interface AnnotationTaskItem {
  id: string
  task_type: string
  target_type: string
  target_id: string
  secondary_target_id?: string | null
  schema_version: string
  status: string
  priority: number
  reason?: string | null
  context_snapshot: Record<string, unknown>
  prediction_snapshot: Record<string, unknown>
  source_dataset?: string | null
  latest_label?: AnnotationLabelItem | null
  label_count: number
  created_at?: string | null
  updated_at?: string | null
}

export interface AnnotationStats {
  pending: number
  needs_adjudication: number
  labeled: number
  adjudicated: number
  total: number
  by_task_type: Record<string, number>
}

export interface SubmitAnnotationLabel {
  task_type: string
  target_type: AnnotationTargetType
  target_id: string
  secondary_target_id?: string
  schema_version?: string
  label_payload: { value: string; [key: string]: unknown }
  note?: string
  confidence?: number
  annotator?: string
  context_snapshot?: Record<string, unknown>
  prediction_snapshot?: Record<string, unknown>
  independent?: boolean
}

export const annotationsApi = {
  submitLabel: async (body: SubmitAnnotationLabel): Promise<AnnotationLabelItem> => {
    const response = await api.post<AnnotationLabelItem>('/annotations/labels', body)
    return response.data
  },

  getTarget: async (targetType: AnnotationTargetType, targetId: string): Promise<AnnotationTaskItem[]> => {
    const response = await api.get<{ items: AnnotationTaskItem[] }>(
      `/annotations/targets/${targetType}/${encodeURIComponent(targetId)}`,
    )
    return response.data.items
  },

  getStats: async (): Promise<AnnotationStats> => {
    const response = await api.get<AnnotationStats>('/annotations/stats')
    return response.data
  },

  getReviewQueue: async (limit = 100): Promise<{ items: AnnotationTaskItem[]; total: number }> => {
    const response = await api.get<{ items: AnnotationTaskItem[]; total: number }>(
      '/annotations/review-queue',
      { params: { status: 'actionable', limit } },
    )
    return response.data
  },

  adjudicate: async (
    taskId: string,
    value: string,
    rationale: string,
  ): Promise<void> => {
    await api.post(`/annotations/tasks/${taskId}/adjudicate`, {
      final_payload: { value },
      rationale,
      adjudicator: 'local-user',
      gold_candidate: true,
    })
  },
}
