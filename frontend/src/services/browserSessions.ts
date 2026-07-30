import api from './api'

export type BrowserSessionStatus = 'needs_login' | 'unverified' | 'active' | 'expired' | 'error'

export type BrowserSessionMode = 'persistent_profile' | 'storage_state'

export interface BrowserSessionBootstrapMeta {
  at?: string
  final_url?: string
  title?: string
  cookie_count?: number
  headless?: boolean
  fallback_reason?: string
  paragraph_count?: number
  message?: string
  auth_ready?: boolean
  missing_required_cookies?: string[]
}

export interface BrowserSession {
  id: string
  site_url: string
  site_host: string
  profile_name: string
  user_data_dir?: string | null
  storage_state_path?: string | null
  session_mode: BrowserSessionMode
  auth_config_id?: string | null
  status: BrowserSessionStatus
  last_validated_at?: string | null
  last_error?: string | null
  metadata_: {
    last_bootstrap?: BrowserSessionBootstrapMeta
    last_validation?: BrowserSessionBootstrapMeta
    [key: string]: unknown
  }
  created_at?: string
  updated_at?: string
  bootstrap?: {
    final_url?: string
    title?: string
    cookie_count?: number
    auth_ready?: boolean
    missing_required_cookies?: string[]
    message?: string
  }
  validation?: {
    message?: string
    paragraph_count?: number
    cookie_count?: number
    final_url?: string
  }
  bound_sources?: number
  cookies_synced?: boolean
}

export interface BrowserSessionCreate {
  site_url: string
  profile_name?: string
  auth_config_id?: string
  auto_bind_sources?: boolean
}

export interface BrowserSessionOpenLoginPayload {
  /** When false, Playwright opens a visible window and waits for the user to close it. */
  headless?: boolean
  /** If true, seed the profile with cookies from the bound AuthConfig before opening. */
  bootstrap_auth_cookies?: boolean
  /** Upper bound in seconds. For headful mode, the user usually closes the window earlier. */
  dwell_seconds?: number
  /** If true (default), sync the resulting cookies back into the linked AuthConfig. */
  sync_cookies_to_auth_config?: boolean
}

export interface BrowserSessionValidatePayload {
  test_url?: string
  min_article_paragraphs?: number
  wait_ms?: number
  sync_cookies_to_auth_config?: boolean
}

export const browserSessionsApi = {
  list: async (): Promise<BrowserSession[]> => {
    const res = await api.get('/configs/browser-sessions')
    return res.data
  },

  create: async (payload: BrowserSessionCreate): Promise<BrowserSession> => {
    const res = await api.post('/configs/browser-sessions', payload)
    return res.data
  },

  openLogin: async (
    id: string,
    payload: BrowserSessionOpenLoginPayload = {},
  ): Promise<BrowserSession> => {
    const res = await api.post(`/configs/browser-sessions/${id}/open-login`, payload, {
      // Headful manual login may take several minutes — disable the axios default timeout.
      timeout: 0,
    })
    return res.data
  },

  validate: async (
    id: string,
    payload: BrowserSessionValidatePayload = {},
  ): Promise<BrowserSession> => {
    const res = await api.post(`/configs/browser-sessions/${id}/validate`, payload, {
      timeout: 0,
    })
    return res.data
  },

  remove: async (id: string): Promise<void> => {
    await api.delete(`/configs/browser-sessions/${id}`)
  },

  bindSources: async (id: string): Promise<BrowserSession> => {
    const res = await api.post(`/configs/browser-sessions/${id}/bind-sources`)
    return res.data
  },
}
