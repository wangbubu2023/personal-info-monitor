// Source types
export type SourceType = 'website' | 'rss' | 'x' | 'youtube' | 'podcast'

export type FetchStatus = 'ok' | 'warning' | 'error' | 'unknown'

/** Result of an explicit URL probe — separate from fetch_status (real grab history). */
export type ProbeStatus = FetchStatus | 'pending' | 'not_probed' | 'failed'

/** Rolling 7-day fetch profile summary (backend: domains.fetch.profile.summarize_profile). */
export interface FetchProfileSummary {
  attempts_7d: number
  success_count_7d: number
  failure_count_7d: number
  empty_count_7d: number
  saved_count_7d: number
  success_rate_7d: number | null
  avg_latency_ms_7d: number | null
  fulltext_success_rate_7d: number | null
  last_success_at?: string | null
  last_failure_at?: string | null
  last_failure_code?: string | null
  preferred_strategy?: string | null
}

/** Circuit-breaker record (backend: metadata.fetch_failure). */
export interface FetchFailureMeta {
  last_code?: string
  last_status?: number | null
  severity?: string
  retryable?: boolean
  cooldown_until?: string
  cooldown_seconds?: number
  consecutive_by_code?: Record<string, number>
  consecutive_failures?: number
  updated_at?: string
}

/** RSS feed health (backend: metadata.rss_health). */
export interface RssHealthMeta {
  status?: 'ok' | 'stale' | 'empty' | 'parse_error'
  healthy?: boolean
  item_count?: number
  last_update?: string | null
  stale_days?: number | null
  reason?: string
  checked_at?: string
  feed_url?: string
}

/** Listing-discovery diagnostics (backend: metadata.discovery_diagnostics). */
export interface DiscoveryDiagnostics {
  total?: number
  kept?: number
  dropped_no_url?: number
  dropped_off_domain?: number
  dropped_deny?: number
  dropped_allow_miss?: number
  dropped_short_title?: number
  dropped_duplicate?: number
  dropped_stale?: number
  truncated?: number
}

export interface SourceMetadata {
  fetch_failure?: FetchFailureMeta
  fetch_profile?: Record<string, unknown>
  rss_health?: RssHealthMeta
  discovery_diagnostics?: DiscoveryDiagnostics
  [key: string]: unknown
}

export interface Source {
  id: string
  name: string
  type: SourceType
  url: string
  extra_urls?: string[]
  fetch_interval: number
  enabled: boolean
  use_keyword_filter: boolean
  auth_required: boolean
  auth_config_id?: string
  last_fetched_at?: string
  last_content_id?: string
  last_error?: string
  error_count: number
  content_count: number
  metadata?: SourceMetadata
  fetch_status: FetchStatus
  fetch_strategy: string
  fetch_status_message: string
  probe_status: ProbeStatus
  probe_strategy: string
  probe_message: string
  probed_at?: string
  // Fetch-health fields surfaced by serialize_source (enhancement plan).
  fetch_profile_summary?: FetchProfileSummary
  last_failure_code?: string | null
  cooldown_until?: string | null
  created_at: string
  updated_at: string
}

export interface SourceCreate {
  name: string
  type: SourceType
  url: string
  extra_urls?: string[]
  fetch_interval?: number
  enabled?: boolean
  use_keyword_filter?: boolean
  auth_required?: boolean
  auth_config_id?: string | null
  metadata?: Record<string, unknown>
}

// Content types
export interface KeywordMatch {
  id: string
  keyword: string
  color?: string
  matched_term?: string
  matched_scope?: KeywordMatchScope
  match_scope?: KeywordMatchScope
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
  is_user_edited?: boolean
  keyword_matches: KeywordMatch[]
  metadata?: Record<string, unknown>
  fetched_at: string
  created_at: string
  updated_at: string
  source_name?: string
}

// Keyword types
export type MatchType = 'exact' | 'contains' | 'regex'
export type KeywordMatchScope = 'title' | 'content' | 'title_content'

export interface Keyword {
  id: string
  keyword: string
  description?: string
  match_type: MatchType
  match_scope: KeywordMatchScope
  case_sensitive: boolean
  manual_equivalent_terms: string[]
  include_auto_equivalent_terms: boolean
  notify: boolean
  notify_email: boolean
  color: string
  enabled: boolean
  equivalent_terms: string[]
  created_at: string
  updated_at: string
}

export interface KeywordCreate {
  keyword: string
  description?: string
  match_type?: MatchType
  match_scope?: KeywordMatchScope
  case_sensitive?: boolean
  manual_equivalent_terms?: string[]
  include_auto_equivalent_terms?: boolean
  notify?: boolean
  notify_email?: boolean
  color?: string
  enabled?: boolean
}

export interface KeywordBatchCreate {
  keywords: string[]
  description?: string
  match_type?: MatchType
  match_scope?: KeywordMatchScope
  case_sensitive?: boolean
  manual_equivalent_terms?: string[]
  include_auto_equivalent_terms?: boolean
  notify?: boolean
  notify_email?: boolean
  color?: string
  enabled?: boolean
}

export interface KeywordBatchCreateResponse {
  items: Keyword[]
  total: number
  skipped_keywords: string[]
}

export interface KeywordBatchUpdate {
  keyword_ids: string[]
  color?: string
  match_scope?: KeywordMatchScope
  match_type?: MatchType
  enabled?: boolean
}

export interface KeywordBatchUpdateResponse {
  items: Keyword[]
  total: number
}

// Digest types
export interface DigestItem {
  id: string
  source_id?: string
  source_name: string
  title: string
  translated_title?: string
  summary?: string
  translated_summary?: string
  /** 摘要过短时由后端从正文截取的列表预览 */
  body_preview?: string
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
    rss: DigestCategory
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

/** 写作模型包含生成参数 */
export interface WritingAIModelConfig extends AIModelConfig {
  temperature: number
  max_tokens: number
  ollama_num_ctx?: number
  ollama_no_think?: boolean
}

/** @deprecated 使用 WritingAIModelConfig */
export type SummaryAIModelConfig = WritingAIModelConfig

export interface SystemSettingsLimits {
  max_sources: number
  max_digest_candidates: number
  max_hourly_digest_input_items: number
}

/** 简报窗口：统一任务提示词与窗口长度 */
export interface HourlyDigestSettings {
  /** 已保存的自定义文案；空字符串表示未自定义（整点任务用内置默认） */
  prompt: string
  /** 旧版兼容字段：生成简报时已不再按入库类型过滤 */
  content_types?: string[]
  window_hours?: number
  /** GET 响应只读：实际用于整点简报的提示词（含内置默认合并结果） */
  prompt_effective?: string
}

export interface FallbackModelPick {
  provider: string
  model: string
}

export interface SystemSettings {
  ai_model: WritingAIModelConfig
  translation_model?: AIModelConfig & {
    ollama_num_ctx?: number
    ollama_no_think?: boolean
  }
  atom_model?: WritingAIModelConfig & {
    ollama_num_ctx?: number
    ollama_no_think?: boolean
  }
  score_model?: WritingAIModelConfig & {
    ollama_num_ctx?: number
    ollama_no_think?: boolean
  }
  translation_enabled: boolean
  title_translation_enabled?: boolean
  auto_translate_language: string
  summarization_enabled: boolean
  translation_fallback_enabled?: boolean
  translation_fallback?: FallbackModelPick
  summarization_fallback_enabled?: boolean
  summarization_fallback?: FallbackModelPick
  /** @deprecated 由后端读时迁移到 translation_fallback_enabled */
  translation_cloud_fallback_enabled?: boolean
  /** @deprecated 由后端读时迁移到 summarization_fallback_enabled */
  summarization_cloud_fallback_enabled?: boolean
  email_notifications_enabled: boolean
  /** Dev-only score lab sidebar entry (ignored in production builds). */
  score_lab_enabled?: boolean
  atoms_enabled?: boolean
  atoms_relations_enabled?: boolean
  limits?: SystemSettingsLimits
  hourly_digest?: HourlyDigestSettings
}

/** Ant Design 表单字段，对应 AIModelTab 提交到 PATCH /configs/settings 的负载 */
export interface AIModelTabFormValues {
  provider: string
  model: string
  temperature: number
  ollama_num_ctx?: number
  ollama_no_think?: boolean
  trans_provider: string
  trans_model: string
  trans_ollama_num_ctx?: number
  trans_ollama_no_think?: boolean
  atom_provider: string
  atom_model: string
  atom_temperature: number
  atom_max_tokens: number
  atoms_enabled?: boolean
  atoms_relations_enabled?: boolean
  atom_ollama_num_ctx?: number
  atom_ollama_no_think?: boolean
  score_provider: string
  score_model: string
  score_temperature: number
  score_max_tokens: number
  score_ollama_num_ctx?: number
  score_ollama_no_think?: boolean
  translation_fallback_enabled: boolean
  trans_fallback_provider: string
  trans_fallback_model: string
  summarization_fallback_enabled: boolean
  sum_fallback_provider: string
  sum_fallback_model: string
  max_sources: number
  max_digest_candidates: number
  max_hourly_digest_input_items: number
}
