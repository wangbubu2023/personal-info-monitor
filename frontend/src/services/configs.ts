import api from './api'

// API Config types
export interface APIConfig {
  id: string
  platform: string
  name?: string
  api_base?: string
  status: string
  last_used_at?: string
  rate_limit_info: Record<string, unknown>
  created_at: string
  updated_at: string
  masked_key?: string
}

export interface APIConfigCreate {
  platform: string
  name?: string
  api_key: string
  api_secret?: string
  additional_config?: Record<string, unknown>
}

// Auth Config types
export interface AuthConfig {
  id: string
  name?: string
  site_url: string
  auth_type: string
  is_shared: boolean
  login_url?: string
  status: string
  last_validated_at?: string
  login_selectors: Record<string, string>
  created_at: string
  updated_at: string
  has_credentials: boolean
  bound_source_count: number
}

export interface AuthConfigCreate {
  name?: string
  site_url: string
  auth_type: string
  is_shared?: boolean
  username?: string
  password?: string
  cookies?: Record<string, string> | string
  login_url?: string
  login_selectors?: Record<string, string>
}

// AI Model types
export interface AIModelProvider {
  id: string
  name: string
  models: { id: string; name: string }[]
  requires_api_key: boolean
  default_api_base?: string
  model_source?: string
  availability_message?: string
}

export interface SystemSettings {
  ai_model: {
    provider: string
    model: string
    api_base?: string
    api_key?: string
    temperature: number
    max_tokens: number
    has_api_key?: boolean
  }
  translation_model?: {
    provider: string
    model: string
    api_base?: string
    api_key?: string
    has_api_key?: boolean
  }
  translation_enabled: boolean
  title_translation_enabled?: boolean
  auto_translate_language: string
  summarization_enabled: boolean
  translation_cloud_fallback_enabled?: boolean
  summarization_cloud_fallback_enabled?: boolean
  email_notifications_enabled: boolean
  limits?: {
    max_sources: number
    max_digest_candidates: number
    max_hourly_digest_input_items: number
  }
}

export const configsApi = {
  // API Keys
  listAPIKeys: async (): Promise<APIConfig[]> => {
    const response = await api.get('/configs/api-keys')
    return response.data
  },

  createAPIKey: async (data: APIConfigCreate): Promise<APIConfig> => {
    const response = await api.post('/configs/api-keys', data)
    return response.data
  },

  updateAPIKey: async (id: string, data: Partial<APIConfigCreate>): Promise<APIConfig> => {
    const response = await api.patch(`/configs/api-keys/${id}`, data)
    return response.data
  },

  deleteAPIKey: async (id: string): Promise<void> => {
    await api.delete(`/configs/api-keys/${id}`)
  },

  // Auth Configs
  listAuthConfigs: async (): Promise<AuthConfig[]> => {
    const response = await api.get('/configs/auth-configs')
    return response.data
  },

  createAuthConfig: async (data: AuthConfigCreate): Promise<AuthConfig> => {
    const response = await api.post('/configs/auth-configs', data)
    return response.data
  },

  updateAuthConfig: async (id: string, data: Partial<AuthConfigCreate>): Promise<AuthConfig> => {
    const response = await api.patch(`/configs/auth-configs/${id}`, data)
    return response.data
  },

  deleteAuthConfig: async (id: string): Promise<void> => {
    await api.delete(`/configs/auth-configs/${id}`)
  },

  // System Settings
  getSettings: async (): Promise<SystemSettings> => {
    const response = await api.get('/configs/settings')
    return response.data
  },

  updateSettings: async (data: Partial<SystemSettings>): Promise<SystemSettings> => {
    const response = await api.patch('/configs/settings', data)
    return response.data
  },

  // Available AI Models
  getAvailableModels: async (): Promise<{ providers: AIModelProvider[] }> => {
    const response = await api.get('/configs/ai-models/available')
    return response.data
  },
}
