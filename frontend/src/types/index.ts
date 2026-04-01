// Source types
export type SourceType = 'website' | 'rss' | 'x' | 'youtube' | 'podcast'

export type FetchStatus = 'ok' | 'warning' | 'error' | 'unknown'

export interface Source {
  id: string
  name: string
  type: SourceType
  url: string
  extra_urls?: string[]
  category_id?: string
  fetch_interval: number
  enabled: boolean
  priority: number
  auth_required: boolean
  auth_config_id?: string
  last_fetched_at?: string
  last_content_id?: string
  last_error?: string
  error_count: number
  metadata?: Record<string, unknown>
  fetch_status: FetchStatus
  fetch_strategy: string
  fetch_status_message: string
  probed_at?: string
  created_at: string
  updated_at: string
}

export interface SourceCreate {
  name: string
  type: SourceType
  url: string
  extra_urls?: string[]
  category_id?: string
  fetch_interval?: number
  enabled?: boolean
  priority?: number
  auth_required?: boolean
  auth_config_id?: string | null
  metadata?: Record<string, unknown>
}

// Content types
export interface KeywordMatch {
  id: string
  keyword: string
  color?: string
}

export interface Content {
  id: string
  source_id: string
  external_id?: string
  title: string
  translated_title?: string
  summary?: string
  translated_summary?: string
  original_url: string
  full_content?: string
  content_type: string
  publish_time?: string
  read_status: boolean
  favorited: boolean
  archived: boolean
  keyword_matches: KeywordMatch[]
  metadata?: Record<string, unknown>
  fetched_at: string
  created_at: string
  updated_at: string
  source_name?: string
}

// Category types
export interface Category {
  id: string
  name: string
  description?: string
  color: string
  icon?: string
  parent_id?: string
  sort_order: number
  created_at: string
  updated_at: string
  source_count: number
  children: Category[]
}

export interface CategoryCreate {
  name: string
  description?: string
  color?: string
  icon?: string
  parent_id?: string
  sort_order?: number
}

// Keyword types
export type MatchType = 'exact' | 'contains' | 'regex'

export interface Keyword {
  id: string
  keyword: string
  description?: string
  match_type: MatchType
  case_sensitive: boolean
  notify: boolean
  notify_email: boolean
  color: string
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface KeywordCreate {
  keyword: string
  description?: string
  match_type?: MatchType
  case_sensitive?: boolean
  notify?: boolean
  notify_email?: boolean
  color?: string
  enabled?: boolean
}

// Digest types
export interface DigestItem {
  id: string
  source_name: string
  title: string
  translated_title?: string
  summary?: string
  translated_summary?: string
  url: string
  publish_time?: string
  fetched_at?: string
  read_status: boolean
  favorited: boolean
  keyword_matches: KeywordMatch[]
  metadata?: Record<string, unknown>
}

export interface DigestCategory {
  count: number
  items: DigestItem[]
}

export interface Digest {
  date: string
  total_items: number
  categories: {
    websites: DigestCategory
    x_accounts: DigestCategory
    youtube: DigestCategory
    podcasts: DigestCategory
  }
}

// Dashboard stats
export interface DashboardStats {
  today_total: number
  unread_count: number
  active_sources: number
  favorited_count: number
}

// Pagination
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

/** AI / translation model block from GET/PATCH /configs/settings */
export interface AIModelConfig {
  provider: string
  model: string
  api_base?: string
  api_key?: string
  has_api_key?: boolean
}

/** 摘要模型包含生成参数 */
export interface SummaryAIModelConfig extends AIModelConfig {
  temperature: number
  max_tokens: number
}

export interface SystemSettingsLimits {
  max_sources: number
  max_digest_candidates: number
  max_hourly_digest_input_items: number
}

export interface SystemSettings {
  ai_model: SummaryAIModelConfig
  translation_model?: AIModelConfig
  translation_enabled: boolean
  title_translation_enabled?: boolean
  auto_translate_language: string
  summarization_enabled: boolean
  translation_cloud_fallback_enabled?: boolean
  summarization_cloud_fallback_enabled?: boolean
  email_notifications_enabled: boolean
  limits?: SystemSettingsLimits
}
