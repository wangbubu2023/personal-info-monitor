import type { SourceType } from '../../types'

export interface CategoryTab {
  key: string
  label: string
  type: SourceType | 'all'
}

export type TranslationStatus = 'idle' | 'generating' | 'ready' | 'failed'

export interface TranslationProgress {
  status: TranslationStatus
  done: number
  total: number
  message?: string
}

export const DASHBOARD_CATEGORIES: CategoryTab[] = [
  { key: 'all', label: '全部', type: 'all' },
  { key: 'websites', label: '网站/博客', type: 'website' },
  { key: 'x_accounts', label: 'X (Twitter)', type: 'x' },
  { key: 'youtube', label: 'YouTube', type: 'youtube' },
]
